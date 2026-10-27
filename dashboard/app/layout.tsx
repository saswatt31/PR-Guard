import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "PR-Guard · Verified test console",
    template: "%s · PR-Guard",
  },
  description:
    "A read-only console for PR-Guard runs: changed TypeScript functions, generated Vitest tests, sandbox evidence and cost.",
};

function ShieldMark() {
  return (
    <svg
      aria-hidden="true"
      className="brand-mark"
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M16 3.5 26 7v7.4c0 6.4-4.1 11.8-10 14.1-5.9-2.3-10-7.7-10-14.1V7l10-3.5Z"
        fill="currentColor"
        opacity="0.16"
      />
      <path
        d="M16 3.5 26 7v7.4c0 6.4-4.1 11.8-10 14.1-5.9-2.3-10-7.7-10-14.1V7l10-3.5Z"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="m11.5 15.7 3.1 3.1 6.1-6.4"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

const publicApiUrl = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <div className="ambient" aria-hidden="true" />
        <header className="site-header">
          <div className="shell header-inner">
            <Link className="brand" href="/">
              <ShieldMark />
              <span className="brand-text">
                PR<span>-</span>Guard
              </span>
              <span className="brand-tag">verified test console</span>
            </Link>
            <nav className="header-nav" aria-label="Console">
              <a className="nav-link" href={`${publicApiUrl}/docs`}>
                API docs
              </a>
              <span className="readonly-pill">
                <span className="pulse-dot" aria-hidden="true" />
                Read only
              </span>
            </nav>
          </div>
        </header>
        <main className="shell page-shell">{children}</main>
        <footer className="site-footer">
          <div className="shell footer-inner">
            <span>PR-Guard · tests are evidence, not suggestions.</span>
            <span className="footer-mono">FastAPI · LangGraph · Docker · Vitest</span>
          </div>
        </footer>
      </body>
    </html>
  );
}
