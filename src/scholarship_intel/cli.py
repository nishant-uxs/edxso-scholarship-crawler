"""CLI: crawl, serve, stats, demo-changes."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from scholarship_intel.pipeline import run_crawl
from scholarship_intel.store import db as store

app = typer.Typer(help="Scholarship Intelligence Crawler")
console = Console()
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "scholarships.db"


@app.command()
def crawl(
    db: Path = typer.Option(DEFAULT_DB, "--db", help="SQLite path"),
    max_pages: int = typer.Option(25, "--max-pages"),
    mark_missing: bool = typer.Option(False, "--mark-missing"),
):
    """Run Discover â†’ Crawl â†’ Extract â†’ Verify â†’ Store."""
    stats = run_crawl(db_path=db, max_discover_pages=max_pages, mark_missing=mark_missing)
    console.print("\n[bold]Crawl finished[/bold]")
    for k, v in stats.items():
        if k != "errors":
            console.print(f"  {k}: {v}")
    if stats.get("errors"):
        console.print(f"  errors: {len(stats['errors'])}")


@app.command()
def stats(db: Path = typer.Option(DEFAULT_DB, "--db")):
    """Print dashboard stats."""
    conn = store.connect(db)
    s = store.dashboard_stats(conn)
    conn.close()
    table = Table(title="Scholarship Intelligence")
    table.add_column("Metric")
    table.add_column("Value")
    for k, v in s.items():
        table.add_row(k, str(v))
    console.print(table)


@app.command("demo-changes")
def demo_changes(db: Path = typer.Option(DEFAULT_DB, "--db")):
    """
    Seed prior values then re-crawl so change detection is demonstrable.

    Simulates a previous crawl that had older deadlines for two schemes,
    then runs a live crawl which writes CHANGE DETECTED events.
    """
    conn = store.connect(db)
    # Ensure we have data
    n = conn.execute("SELECT COUNT(*) c FROM scholarships").fetchone()["c"]
    if n < 5:
        conn.close()
        console.print("Running initial crawl firstâ€¦")
        run_crawl(db_path=db, max_discover_pages=20)

    conn = store.connect(db)
    rows = conn.execute(
        "SELECT id, slug, closing_date, opening_date FROM scholarships "
        "WHERE closing_date IS NOT NULL AND closing_date != 'Not specified' LIMIT 3"
    ).fetchall()
    if len(rows) < 2:
        console.print("[red]Need at least 2 scholarships with closing dates[/red]")
        raise typer.Exit(1)

    # Backdate two closing dates to create a detectable delta on next upsert
    for row in rows[:2]:
        fake_old = "2026-08-31"
        conn.execute(
            "UPDATE scholarships SET closing_date=? WHERE id=?",
            (fake_old, row["id"]),
        )
        console.print(f"  Seeded old closing_date={fake_old} for id={row['id']} ({row['slug'][:40]})")
    conn.commit()
    conn.close()

    console.print("\nRe-crawling to detect changesâ€¦")
    stats = run_crawl(db_path=db, max_discover_pages=15)
    console.print(f"Changed records this run: {stats.get('changed')}")

    conn = store.connect(db)
    changes = conn.execute(
        "SELECT c.*, s.name FROM change_events c "
        "JOIN scholarships s ON s.id=c.scholarship_id "
        "ORDER BY c.detected_at DESC LIMIT 10"
    ).fetchall()
    table = Table(title="Recent change events")
    table.add_column("Scholarship")
    table.add_column("Field")
    table.add_column("Old")
    table.add_column("New")
    for ch in changes:
        table.add_row(ch["name"][:40], ch["field"], str(ch["old_value"])[:24], str(ch["new_value"])[:24])
    console.print(table)
    conn.close()


@app.command()
def serve(
    db: Path = typer.Option(DEFAULT_DB, "--db"),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
):
    """Start the dashboard (FastAPI)."""
    import os

    import uvicorn

    os.environ["SCHOLARSHIP_DB"] = str(db.resolve())
    uvicorn.run("scholarship_intel.web.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
