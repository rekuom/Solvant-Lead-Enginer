import { NextResponse, type NextRequest } from "next/server";
import { DEVICE_COOKIE_NAME } from "@/lib/server/device";

/** Removes this device's access (device cookie and owner session cookies). Re-enable with /setup?key=… */
export async function POST(request: NextRequest) {
  const res = new NextResponse("This device no longer has access.", { status: 200, headers: { "Cache-Control": "no-store" } });
  for (const c of request.cookies.getAll()) {
    if (c.name === DEVICE_COOKIE_NAME || c.name.startsWith("sb-")) res.cookies.set(c.name, "", { path: "/", maxAge: 0 });
  }
  return res;
}
