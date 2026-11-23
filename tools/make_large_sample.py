"""
CurWork Beta 0.013 - DRAFT - For Internal Use (FPT) - large sample maker - modified by: mbitar
Writes a large MADE-UP CUR workbook for load testing: 3,200,000 data rows over 4 sheets
(800,000 per sheet; Excel allows 1,048,576 rows per sheet). Same columns as the small samples.
No customer data. Same output every run (fixed random seed).
Usage: python make_large_sample.py <output.xlsx>
Needs: xlsxwriter (pip install xlsxwriter)
"""
import os, random, sys, time
import xlsxwriter

SHEETS, ROWS_PER_SHEET = 4, 800_000
HEADER = ["bill_billing_period_start_date", "line_item_usage_account_id", "line_item_product_code",
          "product_product_name", "line_item_line_item_type", "line_item_usage_amount",
          "line_item_unblended_cost", None, "SAMPLE DATA - made up, no customer data"]
PRODUCTS = [("AmazonEC2", "Amazon Elastic Compute Cloud"), ("AmazonS3", "Amazon Simple Storage Service"),
            ("AmazonRDS", "Amazon Relational Database Service"), ("AWSLambda", "AWS Lambda"),
            ("AmazonCloudWatch", "AmazonCloudWatch"), ("OCBEnterpriseSupport", "AWS Support (Enterprise)")]
ACCOUNTS = ["000099998888", "007766554433"]          # same made-up agency-b accounts as the small sample
TYPES = ["Usage"] * 18 + ["Tax", "Fee"]              # mostly usage, like a real CUR

def main(out: str) -> None:
    rnd = random.Random(20261022)
    tmp = out + ".part"
    wb = xlsxwriter.Workbook(tmp, {"constant_memory": True})   # streams rows to disk; low memory
    text = wb.add_format({"num_format": "@"})
    bold = wb.add_format({"bold": True})
    start = time.time()
    for s in range(SHEETS):
        ws = wb.add_worksheet("CUR" if s == 0 else f"CUR {s + 1}")
        ws.write_row(0, 0, HEADER, bold)
        for r in range(1, ROWS_PER_SHEET + 1):
            code, name = PRODUCTS[rnd.randrange(6)]
            usage = round(rnd.uniform(0.001, 5000), 4)
            ws.write_string(r, 0, "2026-10-01")
            ws.write_string(r, 1, ACCOUNTS[rnd.randrange(2)], text)
            ws.write_string(r, 2, code)
            ws.write_string(r, 3, name)
            ws.write_string(r, 4, TYPES[rnd.randrange(20)])
            ws.write_number(r, 5, usage)
            ws.write_number(r, 6, round(usage * rnd.uniform(0.01, 3.0), 2))
        print(f"sheet {s + 1} of {SHEETS} done ({time.time() - start:.0f}s)", flush=True)
    wb.close()
    os.replace(tmp, out)
    print(f"DONE {out} {os.path.getsize(out)} bytes, {SHEETS * ROWS_PER_SHEET} data rows, {time.time() - start:.0f}s", flush=True)

if __name__ == "__main__":
    main(sys.argv[1])
