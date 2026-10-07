"use client";

import type { SampleQuery } from "@/lib/samples";

export default function CommandPalette({
  matches,
  activeIndex,
  onPick,
  onHover,
  interpretation,
  onAcceptInterpretation,
  canInterpret
}: {
  matches: SampleQuery[];
  /** Index highlighted by the arrow keys; -1 when the raw input is active. */
  activeIndex: number;
  onPick: (sample: SampleQuery) => void;
  onHover: (index: number) => void;
  /** A translation of what was typed, when it reads as a question. */
  interpretation?: { command: string | null; rationale: string } | null;
  onAcceptInterpretation?: (command: string) => void;
  /** Translation needs an account, because it is metered per plan. */
  canInterpret?: boolean;
}) {
  return (
    <div className="suggestions" data-tour="samples" role="listbox" aria-label="Sample commands">
      {interpretation?.command && onAcceptInterpretation && (
        <button
          type="button"
          className="interpretation"
          // mousedown fires before the blur that would close the palette.
          onMouseDown={(event) => {
            event.preventDefault();
            onAcceptInterpretation(interpretation.command as string);
          }}
        >
          <span className="interpretation-head">
            <em>IN PLAIN ENGLISH</em>
            <code>{interpretation.command}</code>
          </span>
          <small>{interpretation.rationale}</small>
          <span className="interpretation-accept">
            Use this command <span aria-hidden="true">-&gt;</span>
          </span>
        </button>
      )}
      <span>
        SAMPLE QUERIES
        <em>↑↓ to browse · ↵ to load · esc to dismiss</em>
      </span>
      {matches.length ? (
        matches.map((sample, index) => (
          <button
            type="button"
            key={sample.command}
            role="option"
            aria-selected={index === activeIndex}
            className={index === activeIndex ? "active" : ""}
            onMouseEnter={() => onHover(index)}
            // mousedown fires before the input blur that would close the palette.
            onMouseDown={(event) => {
              event.preventDefault();
              onPick(sample);
            }}
          >
            <span className="suggestion-head">
              <code>{sample.command}</code>
              <em>{sample.label}</em>
            </span>
            <span className="suggestion-meta">
              <span className={`docs-role ${sample.role}`}>{sample.role}</span>
              {sample.duration && <span className="docs-duration">{sample.duration}</span>}
            </span>
            <small>{sample.description}</small>
          </button>
        ))
      ) : (
        <p className="suggestion-empty">
          {canInterpret && !interpretation?.command ? (
            <>
              No sample matches that. Describe what you want in plain English and
              a command will be proposed, or see the{" "}
              <a href="/docs#commands">command reference</a>.
            </>
          ) : (
            <>
              No sample matches that. Commands outside the allowlist are rejected —
              see the <a href="/docs#commands">command reference</a>.
            </>
          )}
        </p>
      )}
      <a className="suggestion-docs" href="/docs#samples">
        All sample queries &amp; full reference <span aria-hidden="true">-&gt;</span>
      </a>
    </div>
  );
}
