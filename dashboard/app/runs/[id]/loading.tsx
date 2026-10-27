export default function Loading() {
  return (
    <div aria-label="Loading run" role="status">
      <div className="skeleton" style={{ height: 120, marginBottom: 22 }} />
      <div className="skeleton" />
    </div>
  );
}
