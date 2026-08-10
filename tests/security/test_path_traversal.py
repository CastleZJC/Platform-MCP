"""5.2.2 路径穿越防护验证"""

import pytest

from platform_mcp.common.exceptions import PathSecurityError
from platform_mcp.skills.database.executor import SQLExecutor


class TestPathTraversalProtection:
    def setup_method(self):
        self.executor = SQLExecutor()

    def test_parent_directory_traversal(self):
        with pytest.raises(PathSecurityError):
            self.executor._validate_file_path("../../etc/passwd")

    def test_windows_path_traversal(self):
        with pytest.raises(PathSecurityError):
            self.executor._validate_file_path("..\..\windows\system32\config")

    def test_non_sql_extension(self):
        with pytest.raises(PathSecurityError):
            self.executor._validate_file_path("/tmp/malicious.sh")

    def test_dot_dot_in_middle(self):
        with pytest.raises(PathSecurityError):
            self.executor._validate_file_path("sql/../../../etc/hosts.sql")
