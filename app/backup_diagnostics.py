"""Closed public diagnostics. Never serialize exception text, SQL or inputs."""
from typing import Literal, get_args

ReasonCode = Literal[
    'archive_invalid', 'archive_json_invalid', 'archive_unsafe_entry',
    'archive_entry_count_limit', 'archive_entry_limit', 'archive_manifest_limit',
    'archive_nonregular_entry', 'archive_size_compression_limit', 'archive_format_unsupported',
    'archive_id_invalid', 'archive_manifest_mismatch', 'archive_entry_checksum_mismatch',
    'archive_required_payload_missing', 'archive_checksum_mismatch', 'archive_ownership_mismatch',
    'configuration_invalid', 'configuration_object_expected', 'configuration_row_limit',
    'configuration_payload_limit', 'configuration_resource_checksum_mismatch',
    'configuration_resource_missing', 'configuration_resource_invalid',
    'settings_mode_unsupported', 'not_writable_primary', 'execution_lock_lost', 'job_ownership_lost',
    'pg_client_unavailable', 'pg_dump_failed', 'operation_timeout', 'database_unavailable',
    'storage_full', 'storage_permission_denied', 'storage_read_only', 'storage_unavailable',
    'operation_failed', 'executor_interrupted',
]
FailedStage = Literal['preparing', 'exporting', 'validating_publishing',
                      'verifying_zip_not_restore', 'restoring_settings', 'completed', 'admitted']
REASON_CODES = frozenset(get_args(ReasonCode))
STAGES = frozenset(get_args(FailedStage))

# Messages here are static guard labels, NEVER arbitrary exception strings.
ARCHIVE_GUARDS = {
    'duplicate JSON key': 'archive_json_invalid', 'nonfinite JSON': 'archive_json_invalid',
    'unsafe archive entry': 'archive_unsafe_entry', 'reserved entry': 'archive_unsafe_entry',
    'invalid scope': 'archive_invalid', 'entry count limit': 'archive_entry_count_limit',
    'entry limit': 'archive_entry_limit', 'manifest size limit': 'archive_manifest_limit',
    'duplicate or nonregular entry': 'archive_nonregular_entry',
    'archive size/compression limit': 'archive_size_compression_limit',
    'unsupported backup format': 'archive_format_unsupported', 'invalid archive id': 'archive_id_invalid',
    'manifest entries mismatch': 'archive_manifest_mismatch',
    'entry checksum mismatch': 'archive_entry_checksum_mismatch',
    'missing required payload': 'archive_required_payload_missing',
    'invalid backup archive': 'archive_invalid', 'archive size mismatch': 'archive_invalid',
    'archive checksum mismatch': 'archive_checksum_mismatch',
    'archive ownership mismatch': 'archive_ownership_mismatch',
    'configuration object expected': 'configuration_object_expected',
    'configuration row too large': 'configuration_payload_limit', 'settings row limit': 'configuration_row_limit',
    'settings payload limit': 'configuration_payload_limit',
    'configuration resource checksum mismatch': 'configuration_resource_checksum_mismatch',
    'missing configuration resource': 'configuration_resource_missing',
    'invalid avatar history': 'configuration_resource_invalid',
    'invalid background filename': 'configuration_resource_invalid',
    'resource catalog mismatch': 'configuration_resource_invalid',
    'resource metadata mismatch': 'configuration_resource_invalid',
    'non-configuration resource': 'configuration_resource_invalid',
    'invalid migration digest': 'configuration_invalid', 'invalid legacy route': 'configuration_invalid',
    'public host size': 'configuration_invalid', 'unknown settings class': 'configuration_invalid',
    'unknown shared settings class': 'configuration_invalid', 'settings archive required': 'configuration_invalid',
    'settings payload version': 'configuration_invalid', 'unexpected settings table': 'configuration_invalid',
    'unsafe settings fields': 'configuration_invalid', 'unsafe shared state': 'configuration_invalid',
    'private configuration key': 'configuration_invalid', 'unsafe profile fields': 'configuration_invalid',
    'profile identity missing; use full restore for a new site': 'configuration_invalid',
}


class BackupFailure(RuntimeError):
    def __init__(self, code: ReasonCode):
        self.reason_code = code if code in REASON_CODES else 'operation_failed'
        super().__init__(self.reason_code)
