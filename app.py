# app.py
from flask import Flask, request, render_template
import pandas as pd
from datetime import datetime
import os, math
from jinja2 import Template

app = Flask(__name__)

# ---------------- Configuration ----------------
SCALE_XLSX = "salary_scale.xlsx"

MONTHS = [
    "Mar-2025","Apr-2025","May-2025","Jun-2025",
    "Jul-2025","Aug-2025","Sep-2025","Oct-2025",
    "Nov-2025","Dec-2025","Jan-2026","Feb-2026"
]

DA_RATES = {"Mar-2025":0.1275, "Jul-2025":0.1475}
HRA_RATES = {"A":0.20,"B":0.15,"C":0.075}
CCA_AMOUNT = 600
MEDICAL_AMOUNT = 500

TAX_SLABS = [
    (0,400000,0.0),(400000,800000,0.05),(800000,1200000,0.10),
    (1200000,1600000,0.15),(1600000,2000000,0.20),
    (2000000,2400000,0.25),(2400000,math.inf,0.30)
]
STANDARD_DEDUCTION = 75000
REBATE_87A = 75000

# ---------------- Helpers ----------------
def parse_scale(scale_str):
    parts = scale_str.split('-')
    numbers = [float(p) for p in parts]
    if len(numbers) < 3 or len(numbers) % 2 == 0:
        raise ValueError("Invalid scale format")
    salaries = numbers[0::2]; increments = numbers[1::2]
    ranges = []
    for i in range(len(increments)):
        ranges.append((salaries[i], salaries[i+1], increments[i]))
    return ranges

def load_all_ranges(filename=SCALE_XLSX):
    df = pd.read_excel(filename, sheet_name=0, header=None)
    scales = df[0].dropna().astype(str).tolist()
    return [parse_scale(s.strip()) for s in scales], scales

def calculate_increment_from_scales(salary, all_ranges):
    for row_idx, grade_ranges in enumerate(all_ranges, start=1):
        for start, end, increment in grade_ranges:
            if start <= salary < end:
                return salary + increment, row_idx
    return salary, None

def get_da_rate_for_month(month_str):
    month_dt = datetime.strptime(month_str, "%b-%Y")
    items = sorted(
        [(datetime.strptime(k, "%b-%Y"), v) for k,v in DA_RATES.items()],
        key=lambda x:x[0]
    )
    applicable = 0.0
    for dt, rate in items:
        if month_dt >= dt: applicable = rate
        else: break
    return applicable

def compute_income_tax_new_regime(annual_gross):
    taxable = max(0, annual_gross - STANDARD_DEDUCTION)
    tax = 0.0
    for lower, upper, pct in TAX_SLABS:
        if taxable <= lower:
            break
        taxable_slice = min(taxable, upper) - lower
        if taxable_slice > 0:
            tax += taxable_slice * pct

    # ✅ Apply rebate only if taxable income <= 12,75,000
    rebate = 0.0
    if taxable <= 1275000:
        rebate = min(REBATE_87A, tax)

    tax_after_rebate = max(0, tax - rebate)
    cess = tax_after_rebate * 0.04
    return {
        "taxable_income": taxable,
        "tax_before_rebate": tax,
        "rebate_applied": rebate,
        "tax_after_rebate": tax_after_rebate,
        "cess": cess,
        "total_tax_liability": tax_after_rebate + cess
    }


# ---------------- Core Processing ----------------
def process_salary_form(data):
    # Personal details
    kgid = data.get("kgid","").strip()
    name = data.get("name","").strip()
    pan = data.get("pan","").strip()
    phone = data.get("phone","").strip()
    address = data.get("address","").strip()
    designation = data.get("designation","").strip()
    group = data.get("group","").strip().upper()
    city_grade = data.get("city_grade","").strip().upper()
    
    # Salary & increments
    basic_salary = float(data.get("basic_salary",0))
    increment_month_raw = data.get("increment","").strip()
    timebond_from = data.get("timebondmonth","")
    leave_encashment = data.get("leave_encashment","NO").strip().upper()
    allowance = float(data.get("allowance",0))

    # Parse months
    def parse_month(m_raw):
        if not m_raw: return None
        m,y = m_raw.split('-',1)
        dt = datetime.strptime(m[:3]+"-"+y,"%b-%Y")
        return dt.strftime("%b-%Y")
    increment_month = parse_month(increment_month_raw)
    timebond_from_month = parse_month(timebond_from)

    # Salary calculation
    all_ranges, scale_strings = load_all_ranges()
    rows = []; current_basic = basic_salary; dec_gross=0

    for month in MONTHS:
        # Apply regular increment
        if increment_month and month == increment_month:
            current_basic,_ = calculate_increment_from_scales(current_basic, all_ranges)
        # Apply timebond increment
        if timebond_from_month and month == timebond_from_month:
            current_basic,_ = calculate_increment_from_scales(current_basic, all_ranges)

        da = round(current_basic * get_da_rate_for_month(month),2)
        hra = round(current_basic * HRA_RATES.get(city_grade,0),2)
        cca = CCA_AMOUNT if city_grade in ("A","B") else 0
        medical = 0 if group in ("A","B") else MEDICAL_AMOUNT
        gross = current_basic + da + hra + cca + medical

        if month=="Dec-2025": dec_gross=gross
        rows.append({"Month":month,"Basic":current_basic,"DA":da,"HRA":hra,"CCA":cca,"Medical":medical,"Gross":gross})

    df=pd.DataFrame(rows)
    annual_basic=df["Basic"].sum(); annual_da=df["DA"].sum(); annual_hra=df["HRA"].sum()
    annual_cca=df["CCA"].sum(); annual_medical=df["Medical"].sum(); annual_gross=df["Gross"].sum()

    # Add encashment + allowance
    el_encashment_amount=0
    if leave_encashment=="YES": el_encashment_amount=0.5*dec_gross
    annual_gross_with_all=annual_gross+el_encashment_amount+allowance

    tax_summary=compute_income_tax_new_regime(annual_gross_with_all)

    return {
        "kgid":kgid,"name":name,"pan":pan,"phone":phone,"address":address,"designation":designation,
        "city_grade":city_grade,"group":group,"increment_month":increment_month,"timebond_from":timebond_from_month,
        "leave_encashment":leave_encashment,"monthly_rows":rows,
        "annual_basic":annual_basic,"annual_da":annual_da,"annual_hra":annual_hra,"annual_cca":annual_cca,
        "annual_medical":annual_medical,"annual_gross":annual_gross,
        "allowance":allowance,"el_encashment_amount":el_encashment_amount,
        "annual_gross_with_all":annual_gross_with_all,"tax_summary":tax_summary
    }

# ---------------- Report ----------------
FORM16_TEMPLATE = """
<!doctype html><html><head><meta charset="utf-8"><title>Form16</title>
<style>
body { font-family: Arial; }
table { border-collapse: collapse; width:100%; margin-bottom:15px;}
th,td { border:1px solid #ccc; padding:4px; font-size:12px; }
th { background:#eee; }
td.left { text-align:left; }
.note { font-size:12px; color:#d35400; }
.success { font-size:12px; color:#27ae60; font-weight:bold; }
.highlight { background:#fff9c4; font-weight:bold; }
button { margin:8px; padding:8px 14px; border:none; border-radius:5px; cursor:pointer; }
#printBtn { background:#3498db; color:white; }
#pdfBtn { background:#27ae60; color:white; }
#qrcode { margin-top:20px; text-align:right; }
.disclaimer { font-size:9px; color:red; margin-top:20px; text-align:center; }
</style></head><body>

<div id="reportContent">
<h2>Form 16 - Salary Report (FY 2025-26 | AY 2026-27)</h2>
<p><b>Name:</b> {{name}} | <b>KGID:</b> {{kgid}} | <b>PAN:</b> {{pan}}</p>
<p><b>Designation:</b> {{designation}} | <b>Group:</b> {{group}}</p>

<!-- Monthly Salary Table -->
<table>
<tr><th>Month</th><th>Basic</th><th>DA</th><th>HRA</th><th>CCA</th><th>Medical</th><th>Gross</th></tr>
{% for r in monthly_rows %}
<tr><td class="left">{{r['Month']}}</td><td>{{r['Basic']}}</td><td>{{r['DA']}}</td>
<td>{{r['HRA']}}</td><td>{{r['CCA']}}</td><td>{{r['Medical']}}</td><td>{{r['Gross']}}</td></tr>
{% endfor %}
</table>

<p><b>Annual Gross (without extras):</b> {{annual_gross}}</p>
<p><b>EL Encashment:</b> {{el_encashment_amount}}</p>
<p><b>Other Allowance:</b> {{allowance}}</p>
<p><b>Total Income:</b> {{annual_gross_with_all}}</p>

<!-- Tax Summary -->
<h3>Tax Calculation Summary</h3>
<table id="taxTable">
<tr><th>Particulars</th><th>Amount (INR)</th></tr>
<tr><td>Taxable Income (after Std Deduction)</td><td>{{tax_summary.taxable_income}}</td></tr>
<tr><td>Tax Before Rebate</td><td>{{tax_summary.tax_before_rebate}}</td></tr>
<tr>
  <td>Rebate u/s 87A</td>
  <td>
    {{tax_summary.rebate_applied}}
    {% if tax_summary.rebate_applied > 0 %}
      <span class="success">✔ Rebate applied</span>
    {% elif tax_summary.taxable_income > 1275000 %}
      <span class="note">Rebate not applicable (Income > ₹12,75,000)</span>
    {% endif %}
  </td>
</tr>
<tr><td>Tax After Rebate</td><td>{{tax_summary.tax_after_rebate}}</td></tr>
<tr><td>Health & Education Cess (4%)</td><td>{{tax_summary.cess}}</td></tr>
<tr class="highlight"><td>Total Tax Liability</td><td>{{tax_summary.total_tax_liability}}</td></tr>
</table>

<!-- References Section -->
<h3>Relevant Provisions under Income-tax Act, 1961</h3>
<ul>
  <li><b>Standard Deduction:</b> ₹75,000 allowed for salaried employees (Sec 16(ia)).</li>
  <li><b>Rebate u/s 87A:</b> Available if taxable income ≤ ₹12,75,000 (max ₹75,000 rebate).</li>
  <li><b>Health & Education Cess:</b> 4% applicable on income-tax after rebate.</li>
</ul>

<!-- New Tax Slabs Table -->
<h3>New Tax Regime Slabs (FY 2025-26)</h3>
<table>
<tr><th>Income Range (₹)</th><th>Tax Rate</th></tr>
<tr><td>0 – 4,00,000</td><td>Nil</td></tr>
<tr><td>4,00,001 – 8,00,000</td><td>5%</td></tr>
<tr><td>8,00,001 – 12,00,000</td><td>10%</td></tr>
<tr><td>12,00,001 – 16,00,000</td><td>15%</td></tr>
<tr><td>16,00,001 – 20,00,000</td><td>20%</td></tr>
<tr><td>20,00,001 – 24,00,000</td><td>25%</td></tr>
<tr><td>Above 24,00,000</td><td>30%</td></tr>
</table>
<h4>Scan the QR code to Pay</h4>
<!-- QR Code -->
<div id="qrcode"></div>

<!-- Disclaimer -->
<p class="disclaimer">
This tax calculation is based on the input given by user and may not depict actual tax liability. Please consult a qualified tax professional.
</p>
</div>

<!-- Buttons -->
<div style="text-align:center; margin-top:20px;">
  <button id="printBtn" onclick="printReport()">🖨 Print</button>
  <button id="pdfBtn" onclick="downloadPDF()">⬇ Download PDF</button>
</div>

<!-- JS libs -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>

<script>
// Generate QR code
window.onload = function() {
  new QRCode(document.getElementById("qrcode"), {
    text: "upi://pay?pa=9916207115@ybl&pn=Girish&am=500&cu=INR",
    width: 100,
    height: 100
  });
};

// Fix PDF download with proper scaling
function downloadPDF() {
  const { jsPDF } = window.jspdf;
  const content = document.getElementById("reportContent");
  html2canvas(content, { scale: 2 }).then(canvas => {
    const imgData = canvas.toDataURL("image/png");
    const pdf = new jsPDF("p", "pt", "a4");
    const pageWidth = pdf.internal.pageSize.getWidth();
    const pageHeight = pdf.internal.pageSize.getHeight();
    const imgWidth = pageWidth - 20;
    const imgHeight = canvas.height * imgWidth / canvas.width;
    let position = 20;
    pdf.addImage(imgData, "PNG", 10, position, imgWidth, imgHeight);
    pdf.save("Form16_Report.pdf");
  });
}
</script>
</body></html>
"""


@app.route("/calculate_salary",methods=["POST"])
def calculate_salary_route():
    result=process_salary_form(request.form)
    return Template(FORM16_TEMPLATE).render(**result)

@app.route("/")
def index():
    return render_template("form.html")

if __name__=="__main__":
    app.run(debug=True,port=5000)
