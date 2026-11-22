# CurWork IAM files

> **DRAFT - For Internal Use (FPT)** · Version **Beta 0.011** · Updated 2026-11-22 13:42 UTC · Modified by: mbitar

| File | Use |
|---|---|
| `biller_permission_set_policy.json` | Inline policy for the biller permission set in IAM Identity Center. Replace `BUCKET_NAME`, `REGION`, `ACCOUNT_ID` and `KMS_KEY_ID`. |
| `bucket_policy_additions.json` | Statements to add to the CUR bucket policy: deny requests without TLS, deny TLS older than 1.2. Replace `BUCKET_NAME`. |

The JSON files carry no stamp inside them because IAM policy documents only accept policy elements. This README holds their version and date.
