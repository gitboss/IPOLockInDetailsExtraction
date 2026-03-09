"""
Text file utilities for content validation
"""

import re


def is_blank_text_file(text: str, min_content_chars: int = 50) -> bool:
    """
    Detect if a text file is essentially blank (just page markers and separators)

    Common pattern in blank files:
    --- PAGE 1 ---
    ######################
    --- PAGE 2 ---
    ######################

    Args:
        text: Text content to check
        min_content_chars: Minimum characters of actual content required

    Returns:
        True if file is blank, False if it has meaningful content
    """
    if not text or not text.strip():
        return True

    # Remove common markers and separators
    cleaned = text

    # Remove page markers (e.g., "--- PAGE 1 ---")
    cleaned = re.sub(r'-+\s*PAGE\s+\d+\s*-+', '', cleaned, flags=re.IGNORECASE)

    # Remove separator lines (e.g., "######################")
    cleaned = re.sub(r'#+', '', cleaned)

    # Remove other common separators
    cleaned = re.sub(r'[=_\-*]{3,}', '', cleaned)

    # Remove whitespace
    cleaned = re.sub(r'\s+', '', cleaned)

    # Check if remaining content is below threshold
    actual_content_length = len(cleaned)

    return actual_content_length < min_content_chars


def get_blank_file_stats(text: str) -> dict:
    """
    Get statistics about a text file to help diagnose blank files

    Args:
        text: Text content

    Returns:
        Dictionary with file statistics
    """
    if not text:
        return {
            'total_chars': 0,
            'page_count': 0,
            'actual_content_chars': 0,
            'is_blank': True
        }

    # Count pages
    page_count = len(re.findall(r'-+\s*PAGE\s+\d+\s*-+', text, flags=re.IGNORECASE))

    # Calculate actual content
    cleaned = text
    cleaned = re.sub(r'-+\s*PAGE\s+\d+\s*-+', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'#+', '', cleaned)
    cleaned = re.sub(r'[=_\-*]{3,}', '', cleaned)
    cleaned = re.sub(r'\s+', '', cleaned)

    return {
        'total_chars': len(text),
        'page_count': page_count,
        'actual_content_chars': len(cleaned),
        'is_blank': is_blank_text_file(text)
    }


def test_blank_detection():
    """Test blank file detection with sample data"""

    # Test Case 1: Blank file with multiple pages
    blank_file = """--- PAGE 1 ---


######################

--- PAGE 2 ---


######################

--- PAGE 3 ---


######################
"""

    # Test Case 2: File with actual content
    content_file = """--- PAGE 1 ---
Promoter Holding: 10,000,000
Public Holding: 5,000,000
Others: 500,000
Total: 15,500,000
######################
"""

    # Test Case 3: Minimal content (edge case)
    minimal_file = """--- PAGE 1 ---
ABC
######################
"""

    print("=" * 80)
    print("Blank File Detection Tests")
    print("=" * 80)

    for name, text in [("Blank Multi-Page", blank_file),
                       ("With Content", content_file),
                       ("Minimal Content", minimal_file)]:
        stats = get_blank_file_stats(text)
        is_blank = is_blank_text_file(text)

        print(f"\n{name}:")
        print(f"  Total chars: {stats['total_chars']}")
        print(f"  Page count: {stats['page_count']}")
        print(f"  Actual content chars: {stats['actual_content_chars']}")
        print(f"  Is blank: {is_blank}")
        print(f"  Status: {'[BLANK]' if is_blank else '[HAS CONTENT]'}")


if __name__ == "__main__":
    test_blank_detection()
