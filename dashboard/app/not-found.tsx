import Link from "next/link";

export default function NotFound() {
  return (
    <section className="not-found">
      <p className="eyebrow" style={{ justifyContent: "center" }}>
        404
      </p>
      <h1>No such run.</h1>
      <p>The run id does not exist in this PR-Guard database.</p>
      <Link className="button primary" href="/">
        Back to run console
      </Link>
    </section>
  );
}
