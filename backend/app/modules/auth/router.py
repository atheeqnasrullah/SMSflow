from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.core.config import settings
from app.core.deps import CurrentPrincipal, Principal, client_ip, require_user
from app.core.errors import Forbidden, RateLimited
from app.core.kv import get_kv
from app.modules.auth import service
from app.modules.auth.schemas import (
    AcceptInvitationIn,
    ChangePasswordIn,
    EmailIn,
    LoginIn,
    MeOut,
    RegisterIn,
    ResetPasswordIn,
    SwitchTenantIn,
    TokenIn,
    TokenOut,
    UpdateProfileIn,
)

router = APIRouter(prefix="/auth", tags=["auth"])

CSRF_HEADER = "x-requested-with"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.refresh_cookie_name,
        token,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=True,
        secure=settings.env not in ("local", "test"),
        samesite="lax",
        path="/",  # also lets the Next.js middleware see that a session exists
    )


def _token_out(response: Response, pair: service.TokenPair) -> TokenOut:
    _set_refresh_cookie(response, pair.refresh_token)
    return TokenOut(access_token=pair.access_token, expires_in=pair.expires_in)


def _csrf_check(request: Request) -> None:
    """Cookie-authenticated endpoints require a custom header (blocked cross-site by CORS)."""
    if request.headers.get(CSRF_HEADER) != "SMSFlow":
        raise Forbidden("Missing X-Requested-With header", code="csrf")


async def _login_throttle(request: Request, key: str) -> None:
    kv = get_kv()
    ip = client_ip(request) or "unknown"
    n = await kv.incr(f"auth:{key}:{ip}", ex=60)
    if n > 20:
        raise RateLimited("Too many attempts, try again in a minute", retry_after=60)


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(data: RegisterIn, request: Request, response: Response) -> TokenOut:
    await _login_throttle(request, "register")
    pair = await service.register(data, ip=client_ip(request), user_agent=request.headers.get("user-agent"))
    return _token_out(response, pair)


@router.post("/login", response_model=TokenOut)
async def login(data: LoginIn, request: Request, response: Response) -> TokenOut:
    await _login_throttle(request, "login")
    pair = await service.login(
        data.email, data.password, ip=client_ip(request), user_agent=request.headers.get("user-agent")
    )
    return _token_out(response, pair)


@router.post("/refresh", response_model=TokenOut)
async def refresh(request: Request, response: Response) -> TokenOut:
    _csrf_check(request)
    pair = await service.refresh(
        request.cookies.get(settings.refresh_cookie_name),
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return _token_out(response, pair)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> Response:
    _csrf_check(request)
    await service.logout(request.cookies.get(settings.refresh_cookie_name))
    response = Response(status_code=204)
    response.delete_cookie(settings.refresh_cookie_name, path="/")
    return response


@router.post("/verify-email", status_code=204)
async def verify_email(data: TokenIn) -> Response:
    await service.verify_email(data.token)
    return Response(status_code=204)


@router.post("/resend-verification", status_code=204)
async def resend_verification(principal: Principal = Depends(require_user())) -> Response:
    assert principal.user_id
    await service.resend_verification(principal.user_id)
    return Response(status_code=204)


@router.post("/forgot-password", status_code=204)
async def forgot_password(data: EmailIn, request: Request) -> Response:
    await _login_throttle(request, "forgot")
    await service.forgot_password(data.email)
    return Response(status_code=204)


@router.post("/reset-password", status_code=204)
async def reset_password(data: ResetPasswordIn, request: Request) -> Response:
    await service.reset_password(data.token, data.password, ip=client_ip(request))
    return Response(status_code=204)


@router.post("/change-password", status_code=204)
async def change_password(
    data: ChangePasswordIn, request: Request, principal: Principal = Depends(require_user())
) -> Response:
    assert principal.user_id
    await service.change_password(principal.user_id, data.current_password, data.new_password, ip=client_ip(request))
    return Response(status_code=204)


@router.get("/me", response_model=MeOut)
async def me(principal: Principal = Depends(require_user())) -> MeOut:
    assert principal.user_id
    return await service.me(principal.user_id, principal.tenant_id, principal.role)


@router.patch("/me", response_model=MeOut)
async def update_me(data: UpdateProfileIn, principal: Principal = Depends(require_user())) -> MeOut:
    assert principal.user_id
    await service.update_profile(principal.user_id, full_name=data.full_name, locale=data.locale, phone=data.phone)
    return await service.me(principal.user_id, principal.tenant_id, principal.role)


@router.post("/switch-tenant", response_model=TokenOut)
async def switch_tenant(
    data: SwitchTenantIn, request: Request, response: Response, principal: Principal = Depends(require_user())
) -> TokenOut:
    assert principal.user_id
    pair = await service.switch_tenant(
        principal.user_id, data.tenant_id, ip=client_ip(request), user_agent=request.headers.get("user-agent")
    )
    return _token_out(response, pair)


@router.post("/accept-invitation", response_model=TokenOut)
async def accept_invitation(data: AcceptInvitationIn, request: Request, response: Response) -> TokenOut:
    current_user = None
    if request.headers.get("authorization"):
        from app.core.deps import get_principal

        p: CurrentPrincipal = await get_principal(request)
        current_user = p.user_id
    pair = await service.accept_invitation(
        data.token, current_user_id=current_user, full_name=data.full_name, password=data.password,
        ip=client_ip(request), user_agent=request.headers.get("user-agent"),
    )
    return _token_out(response, pair)
