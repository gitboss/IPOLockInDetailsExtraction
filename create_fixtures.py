"""
Fixture Creator for IPO Lock-in Parser Testing
Creates a test fixture library by copying representative files that cover all edge cases.
"""
import shutil
from pathlib import Path

# Define fixture mappings: (fixture_name, source_path)
NSE_FIXTURES = [
    ("nse_2digit_year.txt", "downloads/nse/pdf/lockin/txt/finalized/BLUEWATER-CML68316_java.txt"),
    ("nse_2digit_numeric.txt", "downloads/nse/pdf/lockin/txt/finalized/EXIMROUTES-CML71887_java.txt"),
    ("nse_4digit_ordinal.txt", "downloads/nse/pdf/lockin/txt/finalized/AAKAAR-CML68761_java.txt"),
    ("nse_numeric_month.txt", "downloads/nse/pdf/lockin/txt/finalized/ARMOUR-CML72428_java.txt"),
    ("nse_numeric_large.txt", "downloads/nse/pdf/lockin/txt/finalized/BRANDMAN-CML72723_java.txt"),
    ("nse_asterisk_space.txt", "downloads/nse/pdf/lockin/txt/finalized/E2ERAIL-CML72125_java.txt"),
    ("nse_na_dates.txt", "downloads/nse/pdf/lockin/txt/finalized/ARUNAYA-CML67869_java.txt"),
    ("nse_na_mixed.txt", "downloads/nse/pdf/lockin/txt/finalized/AVANA-CML72377_java.txt"),
    ("nse_na_minimal.txt", "downloads/nse/pdf/lockin/txt/finalized/DIVINEHIRA-CML67237_java.txt"),
    ("nse_stress_50rows.txt", "downloads/nse/pdf/lockin/txt/finalized/CHANDAN-CML66693_java.txt"),
    ("nse_large_21rows.txt", "downloads/nse/pdf/lockin/txt/finalized/ENCOMPAS-CML71764_java.txt"),
    ("nse_medium_17rows.txt", "downloads/nse/pdf/lockin/txt/finalized/ARCIIL-CML69895_java.txt"),
    ("nse_small_5rows.txt", "downloads/nse/pdf/lockin/txt/finalized/GANGABATH-CML68453_java.txt"),
    ("nse_small_6rows_space.txt", "downloads/nse/pdf/lockin/txt/finalized/ACCPL-CML68079_java.txt"),
    ("nse_mixed_all.txt", "downloads/nse/pdf/lockin/txt/finalized/CEDAAR-CML68951_java.txt"),
    ("nse_ordinals_space.txt", "downloads/nse/pdf/lockin/txt/finalized/ACTIVEINFR-CML67331_java.txt"),
    ("nse_decimal.txt", "downloads/nse/pdf/lockin/txt/finalized/ASHWINI-CML71882_java.txt"),
    ("nse_complex_18.txt", "downloads/nse/pdf/lockin/txt/finalized/CURRENT-CML69976_java.txt"),
    ("nse_numeric_6rows.txt", "downloads/nse/pdf/lockin/txt/finalized/GREENLEAF-CML70708_java.txt"),
    ("nse_numeric_13rows.txt", "downloads/nse/pdf/lockin/txt/finalized/DHARARAIL-CML72071_java.txt"),
    ("nse_medium_13a.txt", "downloads/nse/pdf/lockin/txt/finalized/AARADHYA-CML69579_java.txt"),
    ("nse_medium_13b.txt", "downloads/nse/pdf/lockin/txt/finalized/CSSL-CML71669_java.txt"),
    ("nse_medium_13c.txt", "downloads/nse/pdf/lockin/txt/finalized/CUDML-CML69531_java.txt"),
    ("nse_medium_12.txt", "downloads/nse/pdf/lockin/txt/finalized/CURIS-CML71278_java.txt"),
    ("nse_medium_15a.txt", "downloads/nse/pdf/lockin/txt/finalized/BHADORA-CML69592_java.txt"),
    ("nse_medium_15b.txt", "downloads/nse/pdf/lockin/txt/finalized/EPWINDIA-CML72045_java.txt"),
    ("nse_medium_14.txt", "downloads/nse/pdf/lockin/txt/finalized/CKKRETAIL-CML72656_java.txt"),
    ("nse_medium_10.txt", "downloads/nse/pdf/lockin/txt/finalized/CLASSICEIL-CML69911_java.txt"),
    ("nse_medium_11.txt", "downloads/nse/pdf/lockin/txt/finalized/FWSTC-CML71758_java.txt"),
    ("nse_medium_9.txt", "downloads/nse/pdf/lockin/txt/finalized/BIOPOL-CML72783_java.txt"),
]

BSE_FIXTURES = [
    ("bse_slash_na_ipo.txt", "downloads/bse/pdf/lockin/txt/finalized/544393-INFONATIVE-Annexure-I_java.txt"),
    ("bse_zero_rows.txt", "downloads/bse/pdf/lockin/txt/finalized/544433-VALINDIA-Annexure-I_java.txt"),
    ("bse_large_20rows.txt", "downloads/bse/pdf/lockin/txt/finalized/544463-REPONO-Annexure-I_java.txt"),
    ("bse_stress_42rows.txt", "downloads/bse/pdf/lockin/txt/finalized/544541-SYSTEMATIC-Annexure-I_java.txt"),
    ("bse_dash_numeric.txt", "downloads/bse/pdf/lockin/txt/finalized/544698-HANNAH-Annexure-I_java.txt"),
    ("bse_slash_12rows.txt", "downloads/bse/pdf/lockin/txt/finalized/544329-VANDU-Annexure-I_java.txt"),
    ("bse_single_2digit.txt", "downloads/bse/pdf/lockin/txt/finalized/544343-CNINFOTECH-Annexure-I_java.txt"),
    ("bse_decimal_11rows.txt", "downloads/bse/pdf/lockin/txt/finalized/544412-3BFILMS-Annexure-I_java.txt"),
    ("bse_na_decimal.txt", "downloads/bse/pdf/lockin/txt/finalized/544441-METAINFO-Annexure-I_java.txt"),
    ("bse_dash_15rows.txt", "downloads/bse/pdf/lockin/txt/finalized/544452-SWASTIKAAL-Annexure-I_java.txt"),
    ("bse_slash_na_12.txt", "downloads/bse/pdf/lockin/txt/finalized/544453-MSECL-Annexure-I_java.txt"),
    ("bse_zero_decimal.txt", "downloads/bse/pdf/lockin/txt/finalized/544460-PATELCHEM-Annexure-I_java.txt"),
    ("bse_decimal_15rows.txt", "downloads/bse/pdf/lockin/txt/finalized/544468-BDI-Annexure-I_java.txt"),
    ("bse_decimal_16rows.txt", "downloads/bse/pdf/lockin/txt/finalized/544471-TAKYON-Annexure-I_java.txt"),
    ("bse_slash_na_11.txt", "downloads/bse/pdf/lockin/txt/finalized/544472-MEHUL-Annexure-I_java.txt"),
    ("bse_large_19rows.txt", "downloads/bse/pdf/lockin/txt/finalized/544518-LTELEVATOR-Annexure-I_java.txt"),
    ("bse_large_22rows.txt", "downloads/bse/pdf/lockin/txt/finalized/544520-SAMPAT-Annexure-I_java.txt"),
    ("bse_dash_na_19.txt", "downloads/bse/pdf/lockin/txt/finalized/544531-TRUECOLORS-Annexure-I_java.txt"),
    ("bse_decimal_12rows.txt", "downloads/bse/pdf/lockin/txt/finalized/544535-BHARATROHAN-Annexure-I_java.txt"),
    ("bse_single_slash.txt", "downloads/bse/pdf/lockin/txt/finalized/544539-SOLVEX-Annexure-I_java.txt"),
    ("bse_slash_standard.txt", "downloads/bse/pdf/lockin/txt/finalized/544552-RDGAIL-Annexure-I_java.txt"),
    ("bse_dash_na_15.txt", "downloads/bse/pdf/lockin/txt/finalized/544555-AMEENJI-Annexure-I_java.txt"),
    ("bse_2digit_na.txt", "downloads/bse/pdf/lockin/txt/finalized/544596-SAFECURE-Annexure-I_java.txt"),
    ("bse_dash_na_11.txt", "downloads/bse/pdf/lockin/txt/finalized/544668-NANTA-Annexure-I_java.txt"),
    ("bse_slash_16rows.txt", "downloads/bse/pdf/lockin/txt/finalized/544680-KASTURI-Annexure-I_java.txt"),
    ("bse_zero_slash.txt", "downloads/bse/pdf/lockin/txt/finalized/544331-DAVIN-Annexure-I_java.txt"),
    ("bse_zero_basic.txt", "downloads/bse/pdf/lockin/txt/finalized/544334-INDOBELL-Annexure-I_java.txt"),
    ("bse_decimal_8rows.txt", "downloads/bse/pdf/lockin/txt/finalized/544341-LICL-Annexure-I_java.txt"),
    ("bse_small_5rows.txt", "downloads/bse/pdf/lockin/txt/finalized/544365-SHANMUGA-Annexure-I_java.txt"),
    ("bse_na_6rows.txt", "downloads/bse/pdf/lockin/txt/finalized/544373-NAPSGLOBAL-Annexure-I_java.txt"),
]

def create_fixtures(output_dir="fixtures"):
    """Copy source files to fixture directory organized by exchange."""

    # Create output directories
    nse_path = Path(output_dir) / "nse"
    bse_path = Path(output_dir) / "bse"

    nse_path.mkdir(parents=True, exist_ok=True)
    bse_path.mkdir(parents=True, exist_ok=True)

    print(f"Creating fixtures in: {Path(output_dir).absolute()}\n")

    # Track statistics
    copied = 0
    missing = 0

    # Copy NSE fixtures
    print("NSE Fixtures:")
    for fixture_name, source_path in NSE_FIXTURES:
        src = Path(source_path)
        dst = nse_path / fixture_name

        if src.exists():
            shutil.copy2(src, dst)
            print(f"  ✓ {fixture_name}")
            copied += 1
        else:
            print(f"  ✗ {fixture_name} - SOURCE MISSING: {source_path}")
            missing += 1

    # Copy BSE fixtures
    print("\nBSE Fixtures:")
    for fixture_name, source_path in BSE_FIXTURES:
        src = Path(source_path)
        dst = bse_path / fixture_name

        if src.exists():
            shutil.copy2(src, dst)
            print(f"  ✓ {fixture_name}")
            copied += 1
        else:
            print(f"  ✗ {fixture_name} - SOURCE MISSING: {source_path}")
            missing += 1

    # Summary
    print("\n" + "="*60)
    print(f"Fixtures created: {copied}")
    print(f"Missing sources: {missing}")
    print(f"Total fixtures: {len(NSE_FIXTURES) + len(BSE_FIXTURES)}")
    print(f"NSE: {nse_path.absolute()}")
    print(f"BSE: {bse_path.absolute()}")
    print("="*60)

if __name__ == '__main__':
    create_fixtures()
