import streamlit as st
import pandas as pd
# グラフ表示(matplotlib)
import matplotlib.pyplot as plt

# データ分析関連
df = pd.read_csv('./data/平均気温.csv', index_col='月')
# st.line_chart(df)
# st.bar_vhart(df['2021年'])

# グラフ表示(matplotlib)
fig, ax = plt.subplots()
ax.plot(df.index, df['2021年'])
ax.set_title('matplotlib graph')
st.pyplot(fig)
