import { afterEach, describe, expect, it, vi } from "vitest";
import { api, setAccessToken } from "@/lib/api";

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
});
