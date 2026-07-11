"""
BUFFETT INDICATOR + Z-SCORE TRACKER — THỊ TRƯỜNG CHỨNG KHOÁN VIỆT NAM
=======================================================================

Buffett Indicator = Tổng vốn hóa thị trường (HOSE+HNX+UPCOM) / GDP danh nghĩa (annualized)
Z-score           = (Ratio hiện tại - Mean lịch sử) / Std lịch sử

CÁCH DÙNG
---------
1. Lần đầu: pip install vnstock pandas matplotlib numpy
2. Cập nhật GDP quý mới nhất vào gdp_data.csv khi GSO công bố số liệu (~4 lần/năm).
   Định dạng: quarter,gdp_ty_vnd (đơn vị: tỷ VND, GDP DANH NGHĨA của riêng quý đó,
   KHÔNG phải số lũy kế từ đầu năm)
3. Chạy: python buffett_indicator.py
4. Output:
   - In ra terminal: vốn hóa, GDP annualized, ratio, z-score, đánh giá vùng
   - history.csv: log tích lũy mỗi lần chạy (để z-score chính xác dần theo thời gian)
   - buffett_chart.png: bản chart tĩnh dự phòng (nhét vào Word/báo cáo nếu cần)
   - index.html: dashboard trực quan, TỰ MỞ trong trình duyệt sau khi chạy (trừ khi
     chạy --silent). Dữ liệu được nhúng sẵn từ history.csv, không cần tải file lên tay.
     Đặt tên index.html có chủ đích — publish qua GitHub Pages là dùng được ngay.

Cần có dashboard_template.html cùng thư mục để bước tạo dashboard hoạt động.

Chạy tự động không cần máy luôn bật: đẩy lên GitHub, cho GitHub Actions tự chạy
theo lịch (xem .github/workflows/update.yml + README.md). Muốn chạy hoàn toàn trên
máy riêng thay vì GitHub thì đóng gói bằng PyInstaller + Task Scheduler (cũng có
hướng dẫn trong README.md).

LƯU Ý QUAN TRỌNG
----------------
- vnstock là thư viện cộng đồng, KHÔNG phải API chính thức của Sở GDCK — hàm/API có thể
  đổi theo version. Nếu get_total_market_cap() lỗi, script sẽ cho nhập vốn hóa thủ công
  (lấy số liệu từ cafef.vn/vietstock.vn mục "Vốn hóa toàn thị trường") để pipeline không
  bao giờ đứt hoàn toàn.
- GDP KHÔNG có API tự động đáng tin cậy cho số liệu quý mới nhất của Việt Nam. Đây là
  bước duy nhất cần thao tác tay, khoảng 4 lần/năm.
- Z-score càng có ý nghĩa khi lịch sử càng dài. Ban đầu (vài điểm dữ liệu đầu) z-score
  sẽ không đáng tin — cần chạy tích lũy vài tháng/quý hoặc backfill dữ liệu lịch sử.
"""

import json
import os
import sys
import webbrowser
from datetime import datetime

import numpy as np
import pandas as pd


def app_dir() -> str:
    """
    Thư mục để ĐỌC/GHI dữ liệu người dùng (gdp_data.csv, history.csv, dashboard...).
    - Chạy bằng `python buffett_indicator.py`: thư mục chứa file .py
    - Chạy bằng file .exe đã đóng gói (PyInstaller): thư mục chứa file .exe
      (KHÔNG phải thư mục tạm _MEIPASS mà PyInstaller giải nén ra khi chạy)
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(relative_path: str) -> str:
    """
    Thư mục để ĐỌC file đi kèm trong bản đóng gói (dashboard_template.html).
    PyInstaller giải nén các file --add-data vào thư mục tạm sys._MEIPASS lúc chạy.
    """
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(app_dir(), relative_path)


GDP_FILE = os.path.join(app_dir(), "gdp_data.csv")
HISTORY_FILE = os.path.join(app_dir(), "history.csv")
CHART_FILE = os.path.join(app_dir(), "buffett_chart.png")
DASHBOARD_TEMPLATE = resource_path("dashboard_template.html")
DASHBOARD_OUTPUT = os.path.join(app_dir(), "index.html")

# --silent: dùng khi chạy nền qua Task Scheduler (không có ai ngồi xem cửa sổ).
# Tắt hết các chỗ chờ input() để không bao giờ bị treo vô thời hạn.
SILENT = "--silent" in sys.argv


# ---------------------------------------------------------------------------
# 1. VỐN HÓA TOÀN THỊ TRƯỜNG (TỰ ĐỘNG)
# ---------------------------------------------------------------------------
def get_total_market_cap() -> float:
    """
    Trả về tổng vốn hóa thị trường VN (HOSE+HNX+UPCOM), đơn vị: tỷ VND.
    Dùng vnstock để lấy marketCap của toàn bộ mã trong MỘT lần gọi (bulk screener),
    tránh loop từng mã (chậm + dễ bị rate-limit).
    """
    try:
        from vnstock import Screener

        screener = Screener()
        df = screener.stock(params={"exchangeName": "HOSE,HNX,UPCOM"}, limit=2000)

        if "marketCap" not in df.columns:
            raise KeyError(
                "Không tìm thấy cột 'marketCap' — API vnstock có thể đã đổi cấu trúc."
            )

        total_cap = pd.to_numeric(df["marketCap"], errors="coerce").fillna(0).sum()

        if total_cap <= 0:
            raise ValueError("Tổng vốn hóa tính ra <= 0, dữ liệu có vẻ không hợp lệ.")

        print(f"[OK] Lấy vốn hóa tự động thành công: {len(df)} mã, "
              f"tổng = {total_cap:,.0f} tỷ VND")
        return float(total_cap)

    except Exception as e:
        print(f"[LỖI] Không lấy được vốn hóa tự động qua vnstock: {e}")
        if SILENT:
            raise RuntimeError(
                "Lấy vốn hóa tự động thất bại khi chạy --silent (chạy nền, không hỏi tay "
                "được). Chạy lại thủ công (không có --silent) để nhập vốn hóa bằng tay, "
                "hoặc sửa get_total_market_cap() theo API vnstock hiện hành."
            ) from e
        print("      Vào cafef.vn hoặc vietstock.vn để lấy số 'Vốn hóa toàn thị trường'.")
        while True:
            raw = input("Nhập vốn hóa toàn thị trường thủ công (đơn vị: tỷ VND): ").strip()
            try:
                return float(raw.replace(",", ""))
            except ValueError:
                print("Giá trị không hợp lệ, nhập lại (chỉ số, không chữ).")


# ---------------------------------------------------------------------------
# 2. GDP ANNUALIZED (BÁN TỰ ĐỘNG — ĐỌC TỪ FILE NGƯỜI DÙNG TỰ CẬP NHẬT)
# ---------------------------------------------------------------------------
def get_gdp_annualized() -> float:
    """
    Đọc gdp_data.csv, lấy 4 quý GẦN NHẤT (trailing 4 quarters) và cộng lại
    để ra GDP danh nghĩa annualized (chính xác hơn nhân quý mới nhất x4 vì
    GDP có tính mùa vụ — quý 4 thường cao hơn quý 1-2).
    """
    if not os.path.exists(GDP_FILE):
        raise FileNotFoundError(
            f"Không tìm thấy {GDP_FILE}. Tạo file với 2 cột: quarter,gdp_ty_vnd"
        )

    df = pd.read_csv(GDP_FILE)
    df = df.dropna(subset=["gdp_ty_vnd"]).sort_values("quarter")

    if len(df) == 0:
        raise ValueError(f"{GDP_FILE} chưa có dữ liệu nào — điền ít nhất 1 quý.")

    if len(df) < 4:
        print(f"[CẢNH BÁO] Chỉ có {len(df)} quý dữ liệu GDP, cần tối thiểu 4 quý để "
              f"annualize chính xác. Đang dùng: quý mới nhất x 4 (kém chính xác hơn).")
        latest = df["gdp_ty_vnd"].iloc[-1]
        return float(latest * 4)

    trailing_4q = df["gdp_ty_vnd"].tail(4).sum()
    print(f"[OK] GDP annualized (tổng 4 quý gần nhất: "
          f"{', '.join(df['quarter'].tail(4).tolist())}) = {trailing_4q:,.0f} tỷ VND")
    return float(trailing_4q)


# ---------------------------------------------------------------------------
# 3. GHI LỊCH SỬ + TÍNH Z-SCORE
# ---------------------------------------------------------------------------
def update_history(market_cap: float, gdp_annualized: float, ratio: float) -> pd.DataFrame:
    row = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "market_cap_ty_vnd": market_cap,
        "gdp_annualized_ty_vnd": gdp_annualized,
        "ratio_percent": ratio,
    }

    if os.path.exists(HISTORY_FILE):
        hist = pd.read_csv(HISTORY_FILE)
        hist = pd.concat([hist, pd.DataFrame([row])], ignore_index=True)
    else:
        hist = pd.DataFrame([row])

    hist = hist.drop_duplicates(subset="date", keep="last")
    hist.to_csv(HISTORY_FILE, index=False)
    return hist


def compute_zscore(hist: pd.DataFrame):
    if len(hist) < 5:
        print(f"[CẢNH BÁO] Chỉ có {len(hist)} điểm dữ liệu lịch sử — z-score chưa đáng tin. "
              f"Khuyến nghị >= 30 điểm (backfill lịch sử hoặc chạy tích lũy vài tháng).")

    mean = hist["ratio_percent"].mean()
    std = hist["ratio_percent"].std()

    if std == 0 or np.isnan(std):
        return None

    latest = hist["ratio_percent"].iloc[-1]
    return (latest - mean) / std


def interpret_zscore(z) -> str:
    if z is None:
        return "Chưa đủ dữ liệu để đánh giá."
    if z >= 2:
        return "RẤT CAO so với lịch sử (z >= 2) — vùng định giá căng, rủi ro cao."
    if z >= 1:
        return "CAO so với lịch sử (1 <= z < 2) — thị trường đang định giá đầy."
    if z <= -2:
        return "RẤT THẤP so với lịch sử (z <= -2) — vùng định giá rẻ, biên an toàn lớn."
    if z <= -1:
        return "THẤP so với lịch sử (-2 < z <= -1) — thị trường đang định giá rẻ."
    return "BÌNH THƯỜNG (-1 < z < 1) — quanh vùng trung bình lịch sử."


# ---------------------------------------------------------------------------
# 4. CHART
# ---------------------------------------------------------------------------
def plot_chart(hist: pd.DataFrame):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("[CẢNH BÁO] Chưa cài matplotlib (pip install matplotlib) — bỏ qua chart.")
        return

    if len(hist) < 2:
        print("[CẢNH BÁO] Cần >= 2 điểm dữ liệu để vẽ chart. Bỏ qua lần này.")
        return

    dates = pd.to_datetime(hist["date"])
    ratio = hist["ratio_percent"]
    mean = ratio.mean()
    std = ratio.std()

    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(dates, ratio, color="#1f6feb", linewidth=2, label="Buffett Indicator (%)", zorder=5)
    ax.scatter(dates.iloc[-1], ratio.iloc[-1], color="#1f6feb", s=60, zorder=6)

    if not np.isnan(std) and std > 0:
        ax.axhline(mean, color="gray", linestyle="--", linewidth=1, label="Mean lịch sử")
        ax.axhspan(mean - std, mean + std, color="#1f6feb", alpha=0.15, label="±1 SD", zorder=1)
        ax.axhspan(mean - 2 * std, mean - std, color="#1f6feb", alpha=0.08, zorder=1)
        ax.axhspan(mean + std, mean + 2 * std, color="#1f6feb", alpha=0.08, zorder=1)

    ax.set_title("Buffett Indicator — Vốn hóa thị trường VN / GDP annualized", fontsize=13)
    ax.set_ylabel("Tỷ lệ (%)")
    ax.set_xlabel("Ngày")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(CHART_FILE, dpi=150)
    print(f"[OK] Đã lưu chart: {CHART_FILE}")


# ---------------------------------------------------------------------------
# 5. DASHBOARD (SINH FILE HTML CÓ NHÚNG SẴN DỮ LIỆU THẬT)
# ---------------------------------------------------------------------------
def generate_dashboard(hist: pd.DataFrame) -> str | None:
    """
    Đọc dashboard_template.html, nhúng dữ liệu history.csv trực tiếp vào (thay vì
    bắt người dùng tải file lên tay), ghi ra buffett_dashboard.html cạnh script/.exe.
    """
    if not os.path.exists(DASHBOARD_TEMPLATE):
        print(f"[CẢNH BÁO] Không tìm thấy {DASHBOARD_TEMPLATE} — bỏ qua bước tạo dashboard. "
              f"Tải lại file dashboard_template.html và để cùng thư mục với script/.exe.")
        return None

    with open(DASHBOARD_TEMPLATE, "r", encoding="utf-8") as f:
        html = f.read()

    records = hist[
        ["date", "market_cap_ty_vnd", "gdp_annualized_ty_vnd", "ratio_percent"]
    ].to_dict(orient="records")
    data_json = json.dumps(records, ensure_ascii=False)

    placeholder = "/*__EMBEDDED_DATA__*/ null"
    if placeholder not in html:
        print("[CẢNH BÁO] dashboard_template.html không đúng bản gốc (thiếu placeholder) "
              "— không nhúng được dữ liệu.")
        return None

    html = html.replace(placeholder, f"/*__EMBEDDED_DATA__*/ {data_json}")

    with open(DASHBOARD_OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[OK] Đã tạo dashboard: {DASHBOARD_OUTPUT}")
    return DASHBOARD_OUTPUT


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    print("=" * 70)
    print("BUFFETT INDICATOR + Z-SCORE — THỊ TRƯỜNG CHỨNG KHOÁN VIỆT NAM")
    print("=" * 70)

    market_cap = get_total_market_cap()
    gdp_annualized = get_gdp_annualized()
    ratio = market_cap / gdp_annualized * 100

    hist = update_history(market_cap, gdp_annualized, ratio)
    z = compute_zscore(hist)

    print("-" * 70)
    print(f"Vốn hóa toàn thị trường : {market_cap:,.0f} tỷ VND")
    print(f"GDP annualized          : {gdp_annualized:,.0f} tỷ VND")
    print(f"Buffett Indicator       : {ratio:.1f}%")
    print(f"Z-score                 : {z:.2f}" if z is not None else "Z-score: N/A")
    print(f"Đánh giá                : {interpret_zscore(z)}")
    print("-" * 70)

    plot_chart(hist)
    print(f"Lịch sử đã lưu tại: {HISTORY_FILE} ({len(hist)} điểm dữ liệu)")

    dashboard_path = generate_dashboard(hist)
    if dashboard_path and not SILENT:
        try:
            webbrowser.open("file://" + os.path.abspath(dashboard_path))
            print("[OK] Đã tự mở dashboard trong trình duyệt.")
        except Exception as e:
            print(f"[CẢNH BÁO] Không tự mở được trình duyệt ({e}). "
                  f"Mở tay file: {dashboard_path}")


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
    except Exception as e:
        print(f"\n[LỖI] {e}")
        exit_code = 1
        if not SILENT:
            import traceback
            traceback.print_exc()
    finally:
        # Khi double-click file .exe, cửa sổ console đóng vụt tắt ngay khi chạy xong
        # nên không kịp đọc kết quả/lỗi. Dừng lại chờ Enter, trừ khi chạy nền --silent.
        if not SILENT:
            try:
                input("\nNhấn Enter để đóng cửa sổ này...")
            except Exception:
                pass
    sys.exit(exit_code)
