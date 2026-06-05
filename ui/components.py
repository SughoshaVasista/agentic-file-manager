"""Shared Streamlit UI components."""

from __future__ import annotations

import streamlit as st


def render_header(title: str, subtitle: str) -> None:
    """Render a compact page header."""

    st.title(title)
    st.caption(subtitle)


def render_metric_row(metrics: dict[str, int | str]) -> None:
    """Render metrics across evenly spaced columns."""

    columns = st.columns(len(metrics) or 1)
    for column, (label, value) in zip(columns, metrics.items(), strict=False):
        column.metric(label, value)
