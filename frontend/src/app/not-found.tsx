import Link from 'next/link';

export default function NotFound() {
  return (
    <main id="main" className="center-page">
      <div className="state state-error">
        <h1 className="state-title">Page not found</h1>
        <p className="state-body">There is no page at this address.</p>
        <p>
          <Link href="/" className="btn btn-primary">
            Go to start
          </Link>
        </p>
      </div>
    </main>
  );
}
