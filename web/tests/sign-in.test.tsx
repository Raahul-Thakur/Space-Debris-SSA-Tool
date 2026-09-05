import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import SignIn from "@/components/SignIn";

const { signIn } = vi.hoisted(() => ({ signIn: vi.fn() }));
vi.mock("@/lib/auth", () => ({ signInWithEmail: signIn }));

beforeEach(() => signIn.mockReset());

it("requests a magic link without collecting a password", async () => {
  signIn.mockResolvedValue(undefined);
  render(<SignIn />);

  fireEvent.change(screen.getByLabelText("EMAIL ADDRESS"), {
    target: { value: "viewer@example.com" }
  });
  fireEvent.click(screen.getByRole("button", { name: /send sign-in link/i }));

  expect(signIn).toHaveBeenCalledWith("viewer@example.com");
  expect(await screen.findByText(/check your inbox/i)).toBeInTheDocument();
  expect(screen.getByText(/illustrative/i)).toBeInTheDocument();
});
