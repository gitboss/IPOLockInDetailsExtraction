import os
import glob

def create_fixture(input_pattern, output_file):
    files = glob.glob(input_pattern, recursive=True)
    seen_lines = set()
    unique_lines = []
    
    for file in files:
        with open(file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                # We optionally strip whitespace for comparison, but maybe keep original for fixture
                clean_line = line.strip()
                if clean_line and clean_line not in seen_lines:
                    seen_lines.add(clean_line)
                    unique_lines.append(line)  # preserve original line with newline
                    
    with open(output_file, 'w', encoding='utf-8') as f:
        for line in unique_lines:
            f.write(line)
            
    print(f"Created {output_file} with {len(unique_lines)} unique lines from {len(files)} files.")

if __name__ == '__main__':
    bse_pattern = 'f:/python/IPOLockInDetailsExtraction/downloads/bse/pdf/lockin/txt/**/*_java.txt'
    nse_pattern = 'f:/python/IPOLockInDetailsExtraction/downloads/nse/pdf/lockin/txt/**/*_java.txt'
    
    create_fixture(bse_pattern, 'f:/python/IPOLockInDetailsExtraction/bse_lockin_fixture_java.txt')
    create_fixture(nse_pattern, 'f:/python/IPOLockInDetailsExtraction/nse_lockin_fixture_java.txt')
