from datetime import date
from pathlib import Path
from statistics import mean, median


def summarize(amounts: list[int]) -> dict:
    """Summarize the observed amounts in piastres."""
    count = len(amounts)
    return {
        "count": count,
        "total_piastres": sum(amounts),
        "mean_piastres": mean(amounts) if count else None,
        "median_piastres": median(amounts) if count else None,
        "range_piastres": max(amounts) - min(amounts) if count else None,
    }


def render_monthly_chart(rows: list[tuple[str, int]], destination: Path) -> None:
    """Save monthly revenue in EGP as a PNG, leaving unobserved months blank."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.dates import AutoDateLocator, DateFormatter
    from matplotlib.figure import Figure

    figure = Figure(figsize=(8, 4.5), layout="constrained")
    canvas = FigureCanvasAgg(figure)
    axes = figure.subplots()
    axes.set_title("Monthly revenue")
    axes.set_xlabel("Month")
    axes.set_ylabel("Revenue (EGP)")
    axes.grid(axis="y", alpha=0.25)
    axes.set_axisbelow(True)

    if rows:
        months = []
        revenue = []
        for month, amount in sorted(rows):
            months.append(date.fromisoformat(f"{month}-01"))
            revenue.append(amount / 100)

        axes.bar(months, revenue, width=21, color="#286b9e")
        zero_months = [month for month, amount in zip(months, revenue) if amount == 0]
        axes.plot(zero_months, [0] * len(zero_months), "o", color="#286b9e")
        axes.set_xlabel("Month\nMissing months are blank. Dots mark observed zero totals.")
        axes.xaxis.set_major_formatter(DateFormatter("%Y-%m"))
        if len(months) <= 12:
            axes.set_xticks(months)
        else:
            axes.xaxis.set_major_locator(AutoDateLocator(minticks=4, maxticks=10))
        axes.tick_params(axis="x", labelrotation=45)
    else:
        axes.set_xticks([])
        axes.set_yticks([])
        axes.text(
            0.5, 0.5, "No monthly observations",
            ha="center", va="center", transform=axes.transAxes,
        )

    canvas.print_png(destination)
