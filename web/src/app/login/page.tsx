import { redirect } from "next/navigation";

/** The old sign-in page: this private tool now uses one-time device authorisation. */
export default function LoginPage() {
  redirect("/device");
}
