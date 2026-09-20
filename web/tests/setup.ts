import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Vitest runs without globals here, so React Testing Library's automatic
// cleanup never registers itself. Without this, rendered trees from earlier
// tests stay in the document and queries match more than one element.
afterEach(cleanup);
