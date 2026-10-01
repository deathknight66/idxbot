with open('dashboard.py', 'r', encoding='utf-8') as f:
    text = f.read()

start_str = '        fig = go.Figure()'
end_str = '        st.plotly_chart(\n            fig,\n            use_container_width=True,\n        )'

if start_str in text and end_str in text:
    before = text.split(start_str)[0]
    after = text.split(end_str)[1]
    
    chart_code = '''        # --- TRADINGVIEW STYLE CHART ---
        from plotly.subplots import make_subplots
        
        fig = make_subplots(
            rows=2, cols=1, 
            shared_xaxes=True, 
            vertical_spacing=0.03,
            row_heights=[0.75, 0.25]
        )
        
        # 1. Candlestick
        fig.add_trace(go.Candlestick(
            x=df.index,
            open=df['open'], high=df['high'], low=df['low'], close=df['close'],
            name='Price',
            increasing_line_color='#26a69a', increasing_fillcolor='#26a69a',
            decreasing_line_color='#ef5350', decreasing_fillcolor='#ef5350'
        ), row=1, col=1)
        
        # 2. Moving Averages & Bollinger
        fig.add_trace(go.Scatter(x=df.index, y=df['ma20'], name='MA20', line=dict(color='#2962FF', width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['ma50'], name='MA50', line=dict(color='#FF6D00', width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['bb_upper'], name='BB Up', line=dict(color='rgba(150, 150, 150, 0.5)', width=1, dash='dash')), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['bb_lower'], name='BB Low', line=dict(color='rgba(150, 150, 150, 0.5)', width=1, dash='dash')), row=1, col=1)
        
        # 3. Volume
        vol_colors = ['#26a69a' if row['close'] >= row['open'] else '#ef5350' for _, row in df.iterrows()]
        fig.add_trace(go.Bar(
            x=df.index, y=df['volume'],
            name='Volume', marker_color=vol_colors, opacity=0.8
        ), row=2, col=1)
        
        # 4. Styling ala TradingView
        fig.update_layout(
            template='plotly_dark',
            height=650,
            margin=dict(l=10, r=10, t=40, b=10),
            xaxis_rangeslider_visible=False,
            showlegend=False,
            title=dict(text=f'<b>{symbol} | Advanced Chart</b>', font=dict(size=20, color='#D1D4DC')),
            paper_bgcolor='#131722',
            plot_bgcolor='#131722',
            hovermode='x unified'
        )
        
        fig.update_xaxes(showgrid=True, gridcolor='#363a45', tickfont=dict(color='#787b86'))
        fig.update_yaxes(showgrid=True, gridcolor='#363a45', tickfont=dict(color='#787b86'), row=1, col=1)
        fig.update_yaxes(showgrid=False, tickfont=dict(color='#787b86'), row=2, col=1)
        
        st.plotly_chart(fig, use_container_width=True)'''
    with open('dashboard.py', 'w', encoding='utf-8') as f:
        f.write(before + chart_code + after)
    print('Chart upgraded')
else:
    print('Target not found')
