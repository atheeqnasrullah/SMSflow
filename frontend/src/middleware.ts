import { NextResponse, type NextRequest } from "next/server";

// Protect the dashboard and admin route groups. The refresh cookie is HttpOnly; its presence only
// means "a session may exist" – the API still validates every request.
const PROTECTED = [
  "/overview",
  "/contacts",
  "/campaigns",
  "/messages",
  "/templates",
  "/reports",
  "/billing",
  "/developers",
  "/settings",
  "/admin",
];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (PROTECTED.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    if (!req.cookies.get("sf_refresh")) {
      const url = req.nextUrl.clone();
      url.pathname = "/login";
      url.search = `?next=${encodeURIComponent(pathname)}`;
      return NextResponse.redirect(url);
    }
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|health).*)"],
};
