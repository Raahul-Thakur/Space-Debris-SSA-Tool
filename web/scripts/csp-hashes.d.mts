// Types for csp-hashes.mjs, which runs under plain Node and is imported by
// the tests.
export const MAX_LINE: number;
export function inlineScripts(html: string): string[];
export function sha256Source(text: string): string;
export function withHashes(policy: string, hashes: string[]): string;
export function routeFor(file: string): string;
export function addInlineScriptHashes(headers: string, pages: Map<string, string>): string;
export function hashExport(outDir: string): Promise<number>;
