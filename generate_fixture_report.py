"""
Generate HTML report from fixture files
Creates a visual report showing all parsed fixture data in a table format.
"""
from pathlib import Path
from datetime import datetime
from lockin_parser_production_unified import parse_lockin_table, parse_bse_text

FIXTURES_DIR = "fixtures"
OUTPUT_FILE = "fixture_report.html"

def parse_fixture(fixture_path):
    """Parse a fixture file and return results."""
    with open(fixture_path, 'r', encoding='utf-8') as f:
        text = f.read()

    # Determine parser based on parent directory
    exchange = fixture_path.parent.name.upper()
    if exchange == 'BSE':
        result = parse_bse_text(text)
    else:  # NSE
        result = parse_lockin_table(text)

    return exchange, result

def generate_html_report():
    """Generate HTML report from all fixtures."""
    fixtures_path = Path(FIXTURES_DIR)

    if not fixtures_path.exists():
        print(f"Error: Fixtures directory not found: {fixtures_path}")
        print("Run create_fixtures.py first!")
        return

    # Scan both nse/ and bse/ subdirectories
    nse_files = sorted((fixtures_path / "nse").glob("*.txt")) if (fixtures_path / "nse").exists() else []
    bse_files = sorted((fixtures_path / "bse").glob("*.txt")) if (fixtures_path / "bse").exists() else []
    fixture_files = nse_files + bse_files

    if not fixture_files:
        print("No fixture files found!")
        return

    # Start HTML
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Fixture Test Report</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        h1 {{
            color: #333;
        }}
        .summary {{
            background: white;
            padding: 15px;
            margin-bottom: 20px;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: white;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}
        th {{
            background-color: #4CAF50;
            color: white;
            padding: 12px;
            text-align: left;
            position: sticky;
            top: 0;
        }}
        td {{
            padding: 10px;
            border-bottom: 1px solid #ddd;
        }}
        tr:hover {{
            background-color: #f5f5f5;
        }}
        .match {{
            color: green;
            font-weight: bold;
        }}
        .mismatch {{
            color: red;
            font-weight: bold;
        }}
        .error {{
            background-color: #ffebee;
        }}
        .warning {{
            background-color: #fff9c4;
        }}
        .sample-rows {{
            font-size: 0.9em;
            color: #666;
        }}
        .nse {{
            background-color: #e3f2fd;
        }}
        .bse {{
            background-color: #fff3e0;
        }}
    </style>
</head>
<body>
    <h1>Fixture Test Report</h1>
    <div class="summary">
        <strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br>
        <strong>Total Fixtures:</strong> {len(fixture_files)}<br>
        <strong>NSE:</strong> {len(nse_files)} | <strong>BSE:</strong> {len(bse_files)}
    </div>

    <table>
        <thead>
            <tr>
                <th>Exchange</th>
                <th>Fixture File</th>
                <th>Rows</th>
                <th>Free</th>
                <th>Locked</th>
                <th>Computed Total</th>
                <th>Declared Total</th>
                <th>Match</th>
                <th>Distinct Errors</th>
                <th>Sample Rows</th>
            </tr>
        </thead>
        <tbody>
"""

    # Process each fixture
    for fixture_file in fixture_files:
        fixture_name = fixture_file.name

        try:
            exchange, result = parse_fixture(fixture_file)
            rows = result.get('rows', [])

            total_rows = len(rows)
            free_count = sum(1 for r in rows if r.get('is_free', False))
            locked_count = total_rows - free_count
            computed_total = sum(r['shares'] for r in rows)
            declared_total = result.get('declared_total')

            # Check for match
            if declared_total:
                match = computed_total == declared_total
                match_cell = f'<span class="{"match" if match else "mismatch"}">{"✓ MATCH" if match else "✗ MISMATCH"}</span>'
            else:
                match_cell = '<span style="color: gray;">N/A</span>'

            # Get sample rows with distinctive number verification
            sample_rows_html = ""
            distinctive_errors = 0
            if rows:
                samples = []
                for i, r in enumerate(rows[:3]):
                    shares = r['shares']
                    from_num = r.get('from', 0)
                    to_num = r.get('to', 0)
                    date = r.get('lockin_date') or r.get('to_date') or 'Free'

                    # Verify shares match distinctive numbers
                    if from_num and to_num:
                        expected_shares = to_num - from_num + 1
                        if expected_shares != shares:
                            samples.append(f'<span style="color: red;">{shares:,} ≠ {expected_shares:,}</span> ({date})')
                            distinctive_errors += 1
                        else:
                            samples.append(f"{shares:,} ({date})")
                    else:
                        samples.append(f"{shares:,} ({date})")

                sample_rows_html = "<br>".join(samples)
                if total_rows > 3:
                    sample_rows_html += f"<br>... +{total_rows - 3} more"

                # Check all rows for distinctive number mismatches
                for r in rows:
                    from_num = r.get('from', 0)
                    to_num = r.get('to', 0)
                    if from_num and to_num:
                        expected_shares = to_num - from_num + 1
                        if expected_shares != r['shares']:
                            distinctive_errors += 1

            # Determine row class
            row_class = exchange.lower()
            if distinctive_errors > 0:
                row_class += " error"  # Red for distinctive number errors
            elif declared_total and computed_total != declared_total:
                row_class += " warning"  # Yellow for total mismatch

            # Format declared total
            declared_total_str = f"{declared_total:,}" if declared_total else "N/A"

            # Format distinctive errors
            distinctive_cell = f'<span class="mismatch">✗ {distinctive_errors}</span>' if distinctive_errors > 0 else '<span class="match">✓ 0</span>'

            # Add table row
            html += f"""
            <tr class="{row_class}">
                <td><strong>{exchange}</strong></td>
                <td>{fixture_name}</td>
                <td>{total_rows}</td>
                <td>{free_count}</td>
                <td>{locked_count}</td>
                <td><strong>{computed_total:,}</strong></td>
                <td>{declared_total_str}</td>
                <td>{match_cell}</td>
                <td>{distinctive_cell}</td>
                <td class="sample-rows">{sample_rows_html}</td>
            </tr>
"""

        except Exception as e:
            html += f"""
            <tr class="error">
                <td colspan="9">
                    <strong>ERROR:</strong> {fixture_name}<br>
                    <span style="color: red;">{str(e)}</span>
                </td>
            </tr>
"""

    # Close HTML
    html += """
        </tbody>
    </table>
</body>
</html>
"""

    # Write to file
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"HTML report generated: {Path(OUTPUT_FILE).absolute()}")
    print(f"Open in browser to view")

if __name__ == '__main__':
    generate_html_report()
