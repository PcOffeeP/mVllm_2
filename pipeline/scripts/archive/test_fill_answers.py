#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal tests for fill_answers.py"""

from fill_answers import generate_answer

# Test 1: Normal time
assert '"time": "38.65s"' in generate_answer('zh_time', '38.65s', '韧性断裂', '')
assert '"type": "韧性断裂"' in generate_answer('zh_mode', '38.65s', '韧性断裂', '')

# Test 2: No fracture
assert '未发生断裂' in generate_answer('zh_time', '未断裂s', '未断裂', '')
assert 'no fracture occurred' in generate_answer('en_time', '未断裂s', '未断裂', '')

# Test 3: Video anomaly
assert '视频异常' in generate_answer('zh_time', '视频异常s', '视频异常', '')
assert '视频异常' in generate_answer('zh_mode', '视频异常s', '视频异常', '')

# Test 4: Indistinguishable
assert '不可分辨' in generate_answer('zh_time', '不可分辨s', '齐根断裂', '')

# Test 5: None/empty value regression
assert '"type"' in generate_answer('zh_both', None, '韧性断裂', '')
assert '"time"' not in generate_answer('zh_both', None, '韧性断裂', '')

# Test 6: Empty string guard (the fix)
result = generate_answer('zh_time', 's', '韧性断裂', '')
assert '"time"' not in result or '""' not in result  # should not produce empty string

print("All tests passed!")
