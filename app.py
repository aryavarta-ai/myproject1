from flask import Flask, render_template, request
from openpyxl import load_workbook

app = Flask(__name__)

# Load salary scales from Excel
def load_salary_scales(filepath="salary_scale.xlsx"):
    wb = load_workbook(filepath, data_only=True)
    ws = wb.active
    scales = []
    for row in ws.iter_rows(min_row=2, values_only=True):  # skip header
        # skip if row is empty or shorter than 3 columns
        if not row or len(row) < 3 or row[0] is None or row[1] is None or row[2] is None:
            continue
        scale = {
            "start": int(row[0]),
            "increment": int(row[1]),
            "end": int(row[2])
        }
        scales.append(scale)
    return scales

salary_scales = load_salary_scales()

# Utility: find next increment
def get_next_increment(basic):
    for scale in salary_scales:
        if scale["start"] <= basic <= scale["end"]:
            next_basic = basic + scale["increment"]
            if next_basic > scale["end"]:
                return scale["end"]
            return next_basic
    return basic  # no change if not found

# Core salary + tax calculation
def calculate_salary(basic_salary, increment_month, allowance, el_encashment_amount):
    monthly_rows = []
    current_basic = basic_salary
    da_rate = 0.1475  # 14.75% DA

    for month in range(1, 13):
        # Apply increment in chosen month
        if month == increment_month:
            current_basic = get_next_increment(current_basic)

        da = round(current_basic * da_rate)
        hra = round(current_basic * 0.1)
        cca = 1000
        medical = 500
        gross = current_basic + da + hra + cca + medical

        monthly_rows.append({
            "Month": month,
            "Basic": current_basic,
            "DA": da,
            "HRA": hra,
            "CCA": cca,
            "Medical": medical,
            "Gross": gross
        })

    # Annual income
    annual_gross = sum([row["Gross"] for row in monthly_rows])
    total_income = annual_gross + allowance + el_encashment_amount

    # Tax (New Regime 2025-26)
    std_deduction = 75000
    taxable_income = max(0, total_income - std_deduction)

    tax = 0
    if taxable_income <= 400000:
        tax = 0
    elif taxable_income <= 800000:
        tax = (taxable_income - 400000) * 0.05
    elif taxable_income <= 1200000:
        tax = 20000 + (taxable_income - 800000) * 0.10
    elif taxable_income <= 1600000:
        tax = 60000 + (taxable_income - 1200000) * 0.15
    elif taxable_income <= 2000000:
        tax = 120000 + (taxable_income - 1600000) * 0.20
    elif taxable_income <= 2400000:
        tax = 200000 + (taxable_income - 2000000) * 0.25
    else:
        tax = 300000 + (taxable_income - 2400000) * 0.30

    rebate_applied = 0
    if taxable_income <= 1275000:
        rebate_applied = min(75000, tax)
        tax -= rebate_applied

    cess = tax * 0.04
    total_tax = tax + cess

    tax_summary = {
        "taxable_income": taxable_income,
        "tax_before_rebate": round(tax + rebate_applied),
        "rebate_applied": round(rebate_applied),
        "tax_after_rebate": round(tax),
        "cess": round(cess),
        "total_tax_liability": round(total_tax)
    }

    return monthly_rows, annual_gross, total_income, tax_summary


# Routes
@app.route("/")
def index():
    return render_template("form.html")

@app.route("/calculate_salary", methods=["POST"])
def process_form():
    try:
        basic_salary = int(request.form["basic_salary"])
        increment_month = int(request.form["increment_month"])
        allowance = int(request.form.get("allowance", 0))
        el_encashment_amount = int(request.form.get("el_encashment_amount", 0))
    except Exception as e:
        return f"Invalid input: {e}"

    monthly_rows, annual_gross, total_income, tax_summary = calculate_salary(
        basic_salary, increment_month, allowance, el_encashment_amount
    )

    return render_template(
        "report.html",
        name=request.form.get("name", ""),
        kgid=request.form.get("kgid", ""),
        pan=request.form.get("pan", ""),
        designation=request.form.get("designation", ""),
        group=request.form.get("group", ""),
        monthly_rows=monthly_rows,
        annual_gross=annual_gross,
        allowance=allowance,
        el_encashment_amount=el_encashment_amount,
        annual_gross_with_all=total_income,
        tax_summary=tax_summary
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

