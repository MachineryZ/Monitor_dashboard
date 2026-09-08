fig.update_layout(
    title=f"【{product_key}】{inst}  (broker: {broker})",
    xaxis=xaxis_dict,
    yaxis=dict(
        title="持仓 (手)",
        autorange=True,
        side="left",
        showgrid=True,
        gridcolor='lightgray',
        zeroline=True,
    ),
    yaxis2=dict(
        title="盈亏 (元)",
        autorange=True,
        side="right",
        overlaying="y",
        showgrid=False,
        zeroline=True,
    ),
    legend=dict(x=0.02, y=0.98, font=dict(size=9)),   # <--- 新增 font.size
    hovermode="x unified",
    height=300,
    margin=dict(l=40, r=40, t=50, b=40),
)