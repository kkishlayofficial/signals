import { redirect } from "next/navigation";

// The Overview dashboard (Phase 7) will own "/" once it exists. Until then
// the terminal is the app's primary screen.
export default function RootPage() {
  redirect("/terminal");
}
