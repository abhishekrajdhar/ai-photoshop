import { NextResponse, type NextRequest } from "next/server";

const PROTECTED = ["/dashboard", "/projects", "/settings"];
const AUTH_PAGES = ["/login", "/register"];

/** Lightweight route protection based on the presence of auth cookies. The API is the real gate. */
export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const hasSession = req.cookies.has("cutpilot_access") || req.cookies.has("cutpilot_refresh");
  if (PROTECTED.some((p) => pathname.startsWith(p)) && !hasSession) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  if (AUTH_PAGES.includes(pathname) && hasSession) {
    const url = req.nextUrl.clone();
    url.pathname = "/dashboard";
    url.search = "";
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = { matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"] };
