import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import SignIn from "@/components/SignIn";

const { request, verify, replace } = vi.hoisted(() => ({
  request: vi.fn(),
  verify: vi.fn(),
  replace: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({
  requestEmailCode: request,
  verifyEmailCode: verify,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

beforeEach(() => {
  request.mockReset().mockResolvedValue(undefined);
  verify.mockReset().mockResolvedValue({});
  replace.mockReset();
});

async function askForCode(address = "operator@example.com") {
  render(<SignIn />);
  fireEvent.change(screen.getByLabelText("EMAIL ADDRESS"), {
    target: { value: address },
  });
  fireEvent.click(screen.getByRole("button", { name: /send code/i }));
  await screen.findByLabelText("SIX-DIGIT CODE");
}

it("asks for a code rather than sending a link", async () => {
  await askForCode();
  expect(request).toHaveBeenCalledWith("operator@example.com");
});

it("exchanges the code for a session and returns to the console", async () => {
  await askForCode();
  fireEvent.change(screen.getByLabelText("SIX-DIGIT CODE"), {
    target: { value: "123456" },
  });
  fireEvent.click(screen.getByRole("button", { name: /^sign in/i }));
  await waitFor(() => expect(verify).toHaveBeenCalledWith("operator@example.com", "123456"));
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
});

it("accepts only digits, and only six of them", async () => {
  await askForCode();
  const field = screen.getByLabelText("SIX-DIGIT CODE") as HTMLInputElement;
  fireEvent.change(field, { target: { value: "12a3b456789" } });
  expect(field.value).toBe("123456");
});

it("will not submit a partial code", async () => {
  await askForCode();
  fireEvent.change(screen.getByLabelText("SIX-DIGIT CODE"), {
    target: { value: "123" },
  });
  expect(screen.getByRole("button", { name: /^sign in/i })).toBeDisabled();
  expect(verify).not.toHaveBeenCalled();
});

it("explains that a rate limit is the project's, not the address's", async () => {
  // Supabase says "email rate limit exceeded", which reads as though the
  // address is at fault and sends people off to try another one. It is a
  // per-project cap and a second address makes no difference.
  request.mockRejectedValueOnce(new Error("email rate limit exceeded"));
  render(<SignIn />);
  fireEvent.change(screen.getByLabelText("EMAIL ADDRESS"), {
    target: { value: "someone@example.com" },
  });
  fireEvent.click(screen.getByRole("button", { name: /send code/i }));
  const message = await screen.findByText(/limit on the platform, not on your address/i);
  expect(message).toBeInTheDocument();
  expect(screen.getByText(/another one will not help/i)).toBeInTheDocument();
});

it("says plainly when a code is wrong or stale", async () => {
  verify.mockRejectedValueOnce(new Error("Token has expired or is invalid"));
  await askForCode();
  fireEvent.change(screen.getByLabelText("SIX-DIGIT CODE"), {
    target: { value: "000000" },
  });
  fireEvent.click(screen.getByRole("button", { name: /^sign in/i }));
  expect(await screen.findByText(/wrong or has expired/i)).toBeInTheDocument();
});

it("blocks a resend during the cooldown rather than letting it be refused", async () => {
  await askForCode();
  expect(screen.getByRole("button", { name: /resend in \d+s/i })).toBeDisabled();
});

it("can start again with a different address", async () => {
  await askForCode();
  fireEvent.click(screen.getByRole("button", { name: /different address/i }));
  expect(await screen.findByLabelText("EMAIL ADDRESS")).toBeInTheDocument();
});

it("keeps the limitations notice on both steps", async () => {
  await askForCode();
  expect(screen.getByText(/must not be used for operational maneuver/i)).toBeInTheDocument();
});
