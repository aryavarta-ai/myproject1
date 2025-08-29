from flask import Flask, render_template, request
from openpyxl import load_workbook

app = Flask(__name__)

# ---------- Load salary scales safely (no pandas) ----------
def load_salary_scales(filepath="salary_scale.xlsx"):
    wb = load_workbook(filepath, data_only=True)
    ws = wb.active
    scales = []
    for row in ws.iter_rows(min_row=2, values_only=True):  # expect: start, increment, end
        if not row or len(row) < 3:
            continue
        start, inc, end = row[0], row[1], row[2]
        if start is None or inc is None or end is None:
            continue
        try:
            scales.append({"start": int(start), "increment": int(inc), "end": int(end)})
        except (TypeError, ValueError):
            continue
    if not scales:
        # fallback to a safe single bracket if file is empty/bad
        scales = [{"start": 10000, "increment": 500, "end": 999999}]
    return scales

SALARY_SCALES = load_salary_scales()

def next_basic_from_scale(basic_now: int) -> int:
    """Return next basic within the matching scale; cap at scale end if exceeded."""
    for s in SALARY_SCALES:
        if s["start"] <= basic_now <= s["end"]:
            nb = basic_now + s["increment"]
            return s["end"] if nb > s["end"] else nb
    return basic_now  # if not found, keep same

# ---------- Components ----------
def hra_amount(basic: int, city_grade: str) -> int:
    if city_grade == "A":
        pct = 0.24
    elif city_grade == "B":
        pct = 0.16
    else:
        pct = 0.10
    return round(basic * pct)

def compute_tax_new_regime(total_income: int, rebate_basis_income: int):
    """
    total_income: annual_gross + allowance + EL encashment (before standard deduction)
    rebate_basis_income: as per your rule for 87A (based on gross incl. extras)
    """
    STD_DED = 75000
    taxable = max(0, total_income - STD_DED)

    # slabs FY 2025-26
    t = 0.0
    if taxable <= 400000:
        t = 0
    elif taxable <= 800000:
        t = (taxable - 400000) * 0.05
    elif taxable <= 1200000:
        t = 20000 + (taxable - 800000) * 0.10
    elif taxable <= 1600000:
        t = 60000 + (taxable - 1200000) * 0.15
    elif taxable <= 2000000:
        t = 120000 + (taxable - 1600000) * 0.20
    elif taxable <= 2400000:
        t = 200000 + (taxable - 2000000) * 0.25
    else:
        t = 300000 + (taxable - 2400000) * 0.30

    # 87A per your requirement: eligibility based on *gross incl. extras* (NOT taxable)
    rebate_applied = 0.0
    if rebate_basis_income <= 1275000:
        rebate_applied = min(75000.0, t)
        t -= rebate_applied

    cess = round(t * 0.04)
    total = round(t + cess)

    return {
        "std_deduction": STD_DED,
        "taxable_income": round(taxable),               # shown in table
        "tax_before_rebate": round(t + rebate_applied),
        "rebate_applied": round(rebate_applied),
        "tax_after_rebate": round(t),
        "cess": cess,
        "total_tax_liability": total,
        "rebate_basis_income": round(rebate_basis_income)  # for reference if you show it
    }

# ---------- Main calculator ----------
def calculate(basic_start: int, inc_month: int, allowance_annual: int,
              timebound_increment: int, city_grade: str):
    """
    - Annual increment applied in chosen inc_month (once).
    - Optional time-bound increment: if >0, apply one more increment in December.
    - HRA depends on city grade (A/B/C).
    - EL Encashment = December Gross (computed).
    """
    monthly_rows = []
    current_basic = int(basic_start)
    DA_RATE = 0.1475
    CCA = 1000
    MEDICAL = 500

    for m in range(1, 13):
        # Annual increment
        if m == inc_month:
            current_basic = next_basic_from_scale(current_basic)

        # Time-bound increment (if opted), applied in December
        if m == 12 and timebound_increment and int(timebound_increment) > 0:
            current_basic = next_basic_from_scale(current_basic)

        da = round(current_basic * DA_RATE)
        hra = hra_amount(current_basic, city_grade)
        gross = current_basic + da + hra + CCA + MEDICAL

        monthly_rows.append({
            "Month": ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][m-1],
            "Basic": current_basic,
            "DA": da,
            "HRA": hra,
            "CCA": CCA,
            "Medical": MEDICAL,
            "Gross": gross
        })

    annual_gross = sum(r["Gross"] for r in monthly_rows)
    december_gross = monthly_rows[-1]["Gross"]  # EL encashment rule
    el_encashment = december_gross

    # total income before standard deduction
    total_income_before_std = annual_gross + int(allowance_annual) + el_encashment

    tax_summary = compute_tax_new_regime(
        total_income=total_income_before_std,
        rebate_basis_income=total_income_before_std   # per your 87A rule (gross incl. extras)
    )

    return {
        "monthly_rows": monthly_rows,
        "annual_gross": annual_gross,
        "allowance": int(allowance_annual),
        "el_encashment_amount": el_encashment,
        "annual_gross_with_all": total_income_before_std,
        "tax_summary": tax_summary
    }

# ---------- Routes ----------
@app.route("/", methods=["GET"])
def index():
    return render_template("form.html")

@app.route("/calculate_salary", methods=["POST"])
def calculate_salary():
    try:
        name = request.form.get("name","").strip()
        kgid = request.form.get("kgid","").strip()
        pan = request.form.get("pan","").strip()
        designation = request.form.get("designation","").strip()
        group = request.form.get("group","").strip()

        basic_salary = int(request.form["basic_salary"])
        increment_month = int(request.form["increment_month"])
        timebound_increment = int(request.form.get("timebound_increment", 0))
        city_grade = request.form.get("city_grade", "C")
        allowance = int(request.form.get("allowance", 0))

    except Exception as e:
        return f"Invalid input: {e}", 400

    result = calculate(
        basic_start=basic_salary,
        inc_month=increment_month,
        allowance_annual=allowance,
        timebound_increment=timebound_increment,
        city_grade=city_grade
    )

    return render_template(
        "report.html",
        name=name, kgid=kgid, pan=pan, designation=designation, group=group,
        monthly_rows=result["monthly_rows"],
        annual_gross=result["annual_gross"],
        allowance=result["allowance"],
        el_encashment_amount=result["el_encashment_amount"],
        annual_gross_with_all=result["annual_gross_with_all"],
        tax_summary=result["tax_summary"]
    )

if __name__ == "__main__":
    # For local testing; Render/Heroku will use gunicorn Procfile
    app.run(host="0.0.0.0", port=5000)
