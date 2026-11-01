import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, isQuotaError, setAccessToken } from "@/lib/api";

describe("api client", () => {
  afterEach(() => {
    setAccessToken(null);
    vi.restoreAllMocks();
  });

  it("adds the verified bearer token", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    setAccessToken("signed-token");

    await api("/auth/me");

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/auth/me"),
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer signed-token" })
      })
    );
  });

  it("surfaces API detail messages", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "analyst role required" }), {
        status: 403,
        headers: { "Content-Type": "application/json" }
      })
    );
    await expect(api("/screening-jobs")).rejects.toThrow("analyst role required");
  });

  it("marks a plan limit so the console can offer an upgrade", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Upgrade to Pro for a higher limit." }), {
        status: 402,
        headers: { "Content-Type": "application/json" }
      })
    );
    const caught = await api("/commands/execute").catch((error: unknown) => error);
    expect(caught).toBeInstanceOf(ApiError);
    expect(isQuotaError(caught)).toBe(true);
    expect(isQuotaError(new ApiError("forbidden", 403))).toBe(false);
  });
});
