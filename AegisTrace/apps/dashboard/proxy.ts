// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
// Visitors without a session see the public introduction at /welcome; signed-in users go straight to
// the dashboard. This is only a routing hint: the API still validates every request.
import { NextResponse, type NextRequest } from "next/server";

export function proxy(request: NextRequest) {
  if (!request.cookies.has("aegis_token")) {
    // Same host the browser used (localhost vs 127.0.0.1 matters for cookies): derive it from nextUrl.
    const url = request.nextUrl.clone();
    url.pathname = "/welcome";
    return NextResponse.redirect(url, 307);
  }
  return NextResponse.next();
}

export const config = { matcher: "/" };
