import unittest

from app.config import Settings


class OcrProxyConfigTests(unittest.TestCase):
    def test_effective_ocr_proxy_disabled_returns_none(self) -> None:
        settings = Settings.model_construct(
            ocr_space_proxy_enabled=False,
            ocr_space_proxy_url='socks5://ocr-proxy',
            telegram_proxy_enabled=True,
            telegram_proxy_url='socks5://telegram-proxy',
        )

        self.assertIsNone(settings.effective_ocr_space_proxy_url)

    def test_effective_ocr_proxy_uses_explicit_proxy_when_enabled(self) -> None:
        settings = Settings.model_construct(
            ocr_space_proxy_enabled=True,
            ocr_space_proxy_url='socks5://ocr-proxy',
            telegram_proxy_enabled=True,
            telegram_proxy_url='socks5://telegram-proxy',
        )

        self.assertEqual(settings.effective_ocr_space_proxy_url, 'socks5://ocr-proxy')

    def test_effective_ocr_proxy_falls_back_to_telegram_proxy(self) -> None:
        settings = Settings.model_construct(
            ocr_space_proxy_enabled=True,
            ocr_space_proxy_url=None,
            telegram_proxy_enabled=True,
            telegram_proxy_url='socks5://telegram-proxy',
        )

        self.assertEqual(settings.effective_ocr_space_proxy_url, 'socks5://telegram-proxy')


if __name__ == '__main__':
    unittest.main()
