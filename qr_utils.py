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
    base_url = (st.secrets.get("APP_BASE_URL") or "").strip()
    if not base_url:
        return  # 非表示

    st.write("---")
    st.subheader("このWebサイトのQRコード")

    buf = BytesIO()
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(base_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(buf, format="PNG")

    # ✅ use_column_width → use_container_width に置き換え
    st.image(buf.getvalue(), caption=base_url, use_container_width=False)
