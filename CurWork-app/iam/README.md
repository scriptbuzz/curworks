# CurWork IAM files

> **DRAFT - For Internal Use (FPT)** · Version **Beta 0.017** · Updated 2026-11-23 01:38 UTC · Modified by: mbitar

| File | Use |
|---|---|
| `biller_permission_set_policy.json` | Inline policy for the biller permission set in IAM Identity Center. Replace `BUCKET_NAME`, `REGION`, `ACCOUNT_ID` and `KMS_KEY_ID`. Its last statement lets billers read CurWork's admin settings in Parameter Store (parameters under `/curwork/`) but not change or delete them. |
| `bucket_policy_additions.json` | Statements to add to the CUR bucket policy: deny requests without TLS, deny TLS older than 1.2. Replace `BUCKET_NAME`. |

The JSON files carry no stamp inside them because IAM policy documents only accept policy elements. This README holds their version and date.

---
*DRAFT - For Internal Use (FPT) · Beta 0.017 · Updated 2026-11-23 01:38 UTC · Modified by: mbitar*
