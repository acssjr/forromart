from __future__ import annotations

"""Shared helpers for obtaining platform tokens via Playwright."""

import asyncio
import threading
from abc import ABC, abstractmethod
from typing import Callable, Optional, Sequence, Tuple

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError, async_playwright


class PlaywrightTokenFetcher(ABC):
    """Base class that automates login and captures authorization headers."""

    network_idle_timeout_ms: int = 180_000

    @property
    @abstractmethod
    def login_url(self) -> str:
        """Initial URL used to start the login flow."""

    @property
    def login_urls(self) -> Sequence[str]:
        """Optional list of login URLs to try, in order of preference."""
        return [self.login_url]

    @property
    def use_firefox(self) -> bool:
        """Override to True to use Firefox instead of Chromium (better anti-detection)."""
        return False

    @property
    @abstractmethod
    def target_endpoints(self) -> Sequence[str]:
        """Endpoints whose requests should carry the authorization header."""

    @abstractmethod
    async def fill_credentials(self, page: Page, username: str, password: str) -> None:
        """Types the provided username and password into the page."""

    @abstractmethod
    async def submit_login(self, page: Page) -> None:
        """Triggers the login form submission."""

    async def dismiss_cookie_banner(self, page: Page) -> None:  # pragma: no cover - UI dependent
        """Best-effort cookie dismissal. Platforms may override for custom behavior."""
        return None

    def fetch_token(
        self,
        username: str,
        password: str,
        *,
        headless: bool = True,
        user_agent: Optional[str] = None,
        wait_for_user_confirmation: Optional[Callable[[], None]] = None,
    ) -> str:
        """
        Synchronously obtains the bearer token after authenticating with credentials.

        When a running event loop is detected (e.g., inside a UI app), the coroutine is
        executed in a background thread to avoid nested-loop errors.
        """

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.fetch_token_async(
                    username,
                    password,
                    headless=headless,
                    user_agent=user_agent,
                    wait_for_user_confirmation=wait_for_user_confirmation,
                )
            )

        return self._fetch_token_in_thread(
            username,
            password,
            headless=headless,
            user_agent=user_agent,
            wait_for_user_confirmation=wait_for_user_confirmation,
        )

    async def fetch_token_async(
        self,
        username: str,
        password: str,
        *,
        headless: bool = True,
        user_agent: Optional[str] = None,
        wait_for_user_confirmation: Optional[Callable[[], None]] = None,
    ) -> str:
        manual_login = not (username and password)

        async with async_playwright() as playwright:
            if self.use_firefox:
                browser = await playwright.firefox.launch(headless=headless)
                ua_to_use = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0"
                context = await browser.new_context(user_agent=ua_to_use)
            else:
                args = ["--disable-blink-features=AutomationControlled"]
                browser = await playwright.chromium.launch(headless=headless, args=args)
                ua_to_use = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                context = await browser.new_context(user_agent=ua_to_use)
                await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            page = await context.new_page()

            try:
                navigation_error: BaseException | None = None

                for candidate in self.login_urls:
                    try:
                        await page.goto(candidate, wait_until="domcontentloaded")
                        await page.wait_for_load_state(
                            "networkidle", timeout=self.network_idle_timeout_ms
                        )
                        break
                    except BaseException as exc:
                        navigation_error = exc
                else:
                    raise navigation_error or RuntimeError("Falha ao abrir a página de login.")

                await self.dismiss_cookie_banner(page)
                auth_task = asyncio.create_task(self._capture_authorization_header(page))

                async def monitor_page():
                    verify_selectors = [
                        "text=/insira o código/i",
                        "text=/digite o código/i",
                        "text=/código de verificação/i",
                        "text=/código enviado/i",
                        "text=/verification code/i",
                        "text=/enter the code/i",
                        "input[placeholder='000000']",
                        "input[name='code']",
                        "input[name='verificationCode']"
                    ]
                    
                    showed_alert = False
                    for _ in range(120): # Monitor for up to 120 seconds
                        if auth_task.done():
                            break
                        try:
                            is_verify_page = False
                            for selector in verify_selectors:
                                try:
                                    if await page.locator(selector).count() > 0 and await page.locator(selector).first.is_visible():
                                        is_verify_page = True
                                        break
                                except Exception:
                                    continue
                            
                            if is_verify_page:
                                if headless:
                                    raise ValueError(
                                        "A plataforma exigiu um código de verificação enviado por e-mail (2FA).\n\n"
                                        "Como o navegador está oculto (modo padrão), o login não pode continuar.\n\n"
                                        "Por favor, marque a opção 'Emular Navegador (2FA/Captcha)' e tente novamente para "
                                        "poder digitar o código de verificação diretamente na janela do navegador."
                                    )
                                elif not showed_alert:
                                    showed_alert = True
                                    import ctypes
                                    import threading
                                    def show_box():
                                        try:
                                            # 0x40 is MB_ICONINFORMATION, 0x2000 is MB_TASKMODAL
                                            ctypes.windll.user32.MessageBoxW(
                                                0,
                                                "Um código de verificação (2FA) foi enviado para o seu e-mail.\n\n"
                                                "Por favor, verifique sua caixa de entrada, digite o código de 6 dígitos na "
                                                "janela do navegador Chrome que foi aberta e conclua o login por lá.\n\n"
                                                "Após concluir o login no navegador, clique em OK no diálogo do aplicativo.",
                                                "Código de Verificação Requerido (2FA)",
                                                0x40 | 0x2000
                                            )
                                        except Exception:
                                            pass
                                    threading.Thread(target=show_box, daemon=True).start()
                                    break # Stop polling once alert is shown
                        except Exception as e:
                            if "closed" in str(e).lower():
                                break
                        await asyncio.sleep(1)

                monitor_task = asyncio.create_task(monitor_page())

                try:
                    if not manual_login:
                        await self.fill_credentials(page, username, password)
                        await self.submit_login(page)

                    # Wait for auth_task, checking for monitor_task errors
                    while not auth_task.done():
                        if monitor_task.done() and monitor_task.exception() is not None:
                            raise monitor_task.exception()
                        await asyncio.sleep(0.5)

                    auth_header, _ = await auth_task
                finally:
                    monitor_task.cancel()

                if not auth_header:
                    raise ValueError("Não foi possível capturar o token de autorização durante o login.")
                return self._strip_bearer_prefix(auth_header)
            finally:
                if wait_for_user_confirmation:
                    try:
                        await asyncio.to_thread(wait_for_user_confirmation)
                    except Exception:
                        pass

                await browser.close()

    def _fetch_token_in_thread(
        self,
        username: str,
        password: str,
        *,
        headless: bool,
        user_agent: Optional[str],
        wait_for_user_confirmation: Optional[Callable[[], None]],
    ) -> str:
        result: list[str] = []
        exc: list[BaseException] = []
        finished = threading.Event()

        def runner() -> None:
            try:
                result.append(
                    asyncio.run(
                        self.fetch_token_async(
                            username,
                            password,
                            headless=headless,
                            user_agent=user_agent,
                            wait_for_user_confirmation=wait_for_user_confirmation,
                        )
                    )
                )
            except BaseException as error:  # pragma: no cover - pass-through error handling
                exc.append(error)
            finally:
                finished.set()

        threading.Thread(target=runner, daemon=True).start()
        finished.wait()

        if exc:
            raise exc[0]

        if not result:
            raise RuntimeError("Falha interna ao capturar o token via Playwright.")

        return result[0]

    async def _capture_authorization_header(self, page: Page) -> Tuple[Optional[str], Optional[str]]:
        def matches_target(url: str) -> bool:
            return any(url.startswith(endpoint) for endpoint in self.target_endpoints)

        try:
            request = await page.wait_for_event(
                "request",
                predicate=lambda r: matches_target(r.url),
                timeout=self.network_idle_timeout_ms,
            )
            self._on_request_captured(request)
            return request.headers.get("authorization"), request.url
        except PlaywrightTimeoutError:
            return None, None

    def _on_request_captured(self, request) -> None:  # pragma: no cover - UI dependent
        """Hook for subclasses to harvest extra headers from the matched request.

        Called with the first request whose URL matches ``target_endpoints``.
        The default implementation is a no-op; platforms that need additional
        headers (e.g. device/2FA tokens) override this and stash them on the
        instance for the platform to read after ``fetch_token`` returns.
        """
        return None

    def _strip_bearer_prefix(self, header: str) -> str:
        prefix = "bearer "
        if header.lower().startswith(prefix):
            return header[len(prefix):].strip()
        return header.strip()
