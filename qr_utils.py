# qr_utils.py
from io import BytesIO
import streamlit as st
import qrcode

def show_qr_simple():
    """
    APP_BASE_URL が設定されていれば「このページのQRコード」を表示。
    - サブヘッダーとバーは QR 表示がある時だけ出す
    - 未設定なら何も表示しない
    """
    url = (st.secrets.get("APP_BASE_URL") or "").strip()
    if not url:
        return

    st.subheader("📱 このページのQRコード")

    buf = BytesIO()
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(url)  # クエリは含めない方針
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(buf, format="PNG")

    st.image(buf.getvalue(), caption=url, use_container_width=False)

    if url.startswith("http://localhost"):
        st.caption("⚠️ localhost は他端末からアクセスできません。スマホ共有は 192.168.x.x:8501 等を使ってください。")
