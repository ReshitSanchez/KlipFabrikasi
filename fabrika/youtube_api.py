"""YouTube OAuth ve servis nesneleri. Her kanal: ayrı Google hesabı + ayrı Cloud projesi + ayrı token."""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import config
from .log import get as get_log

log = get_log("youtube")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
]


class AuthLost(RuntimeError):
    """Kanal erişimi kayboldu (token iptal, hesap kapandı vb.)."""


class QuotaExceeded(RuntimeError):
    pass


def _paths(ch: dict) -> tuple[Path, Path]:
    name = ch["name"]
    return (config.path(ch.get("client_secret") or f"secrets/client_secrets/{name}.json"),
            config.path(ch.get("token") or f"secrets/tokens/{name}.json"))


def credentials(ch: dict):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    _, token_path = _paths(ch)
    if not token_path.exists():
        raise AuthLost(f"{ch['name']} için token yok ({token_path}). 'auth' komutunu çalıştırın.")
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise AuthLost(f"{ch['name']} token yenilenemedi: {e}") from e
        token_path.write_text(creds.to_json())
    return creds


def service(ch: dict, api: str = "youtube", version: str = "v3"):
    from googleapiclient.discovery import build

    return build(api, version, credentials=credentials(ch), cache_discovery=False)


def error_reason(e: Exception) -> str:
    """HttpError içindeki 'reason' alanı."""
    try:
        content = json.loads(e.content.decode("utf-8"))  # type: ignore[attr-defined]
        errs = content.get("error", {}).get("errors", [])
        if errs:
            return errs[0].get("reason", "")
        return content.get("error", {}).get("status", "")
    except Exception:  # noqa: BLE001
        return ""


AUTH_REASONS = {"forbidden", "youtubeSignupRequired", "channelClosed", "channelSuspended", "accountClosed",
                "accountSuspended", "authError", "insufficientPermissions", "PERMISSION_DENIED", "UNAUTHENTICATED"}
QUOTA_REASONS = {"quotaExceeded", "uploadLimitExceeded", "dailyLimitExceeded", "rateLimitExceeded"}


def interactive_auth(ch: dict) -> None:
    """Sunucuda tarayıcı olmadan tek seferlik yetkilendirme (adres çubuğundaki adresi yapıştırma yöntemi)."""
    from google_auth_oauthlib.flow import Flow

    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # sadece localhost yönlendirmesi için
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
    secret, token_path = _paths(ch)
    if not secret.exists():
        raise SystemExit(f"\n❌ İstemci dosyası bulunamadı: {secret}\n   SETUP.md'deki 'OAuth istemci dosyası' adımını yapın.\n")
    flow = Flow.from_client_secrets_file(str(secret), scopes=SCOPES, redirect_uri="http://localhost:8085/")
    url, _ = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    print("\n" + "=" * 70)
    print(f" KANAL: {ch['name']}  ({ch['language']})")
    print("=" * 70)
    print("1) Aşağıdaki adresi KENDİ bilgisayarınızın tarayıcısına kopyalayıp açın:\n")
    print(url)
    print("\n2) Bu kanala ait Google hesabıyla giriş yapın ve kanalı seçin, tüm izinlere 'İzin ver' deyin.")
    print("   ('Google bu uygulamayı doğrulamadı' uyarısı çıkarsa: 'Gelişmiş' -> '... sayfasına git (güvenli değil)')")
    print("3) Sonunda tarayıcı 'Bu siteye ulaşılamıyor' diyecek. BU NORMAL.")
    print("   Tarayıcının adres çubuğundaki adresin TAMAMINI kopyalayıp aşağıya yapıştırın ve Enter'a basın.\n")
    resp = input("Adres: ").strip()
    flow.fetch_token(authorization_response=resp)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(flow.credentials.to_json())
    try:
        yt = service(ch)
        me = yt.channels().list(part="snippet", mine=True).execute()
        title = me["items"][0]["snippet"]["title"] if me.get("items") else "(kanal bulunamadı!)"
    except Exception as e:  # noqa: BLE001
        title = f"(kontrol edilemedi: {e})"
    print(f"\n✅ Tamam! Token kaydedildi: {token_path}\n   Bağlanan YouTube kanalı: {title}\n")
