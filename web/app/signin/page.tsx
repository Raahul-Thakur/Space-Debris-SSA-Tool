import SignIn from "@/components/SignIn";

export const metadata = {
  title: "Sign in / ASTRA SSA",
  description: "Request a secure sign-in link to run screenings of your own."
};

/**
 * Signing in is a destination, not a gate.
 *
 * The console itself is readable without an account: the globe, the catalogue
 * and the assessed conjunctions are the public picture. An account is what
 * lets someone act on it, so this page is reached from the console at the
 * point where an action needs one, rather than standing in front of it.
 */
export default function SignInPage() {
  return <SignIn />;
}
