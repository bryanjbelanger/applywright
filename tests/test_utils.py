import pytest
from applywright.utils import generate_dedupe_key, canonicalize_url

def test_canonicalize_url():
    url1 = "https://example.com/job/123?utm_source=test"
    url2 = "https://example.com/job/123"
    assert canonicalize_url(url1) == canonicalize_url(url2)

def test_stable_dedupe_key_generation():
    key1 = generate_dedupe_key("jobcopilot", " Acme Corp ", "Software Engineer", "https://example.com/job?ref=123")
    key2 = generate_dedupe_key("JobCopilot", "acme corp", "software engineer", "https://example.com/job")
    
    assert key1 == key2

def test_different_jobs_have_different_keys():
    key1 = generate_dedupe_key("jobcopilot", "Acme Corp", "Software Engineer", "")
    key2 = generate_dedupe_key("jobcopilot", "Acme Corp", "Data Scientist", "")
    
    assert key1 != key2
