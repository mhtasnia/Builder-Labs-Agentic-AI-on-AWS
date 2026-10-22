# AWS Lab Notes: Kiro CLI + CloudFormation Security Review

Lab goal: use Kiro CLI to find and fix security problems in a CloudFormation template (`security.yaml`), validate it with `cfn-lint`, then ask for compliance advice and prevention tips.

Environment: Code Editor IDE on EC2, working directory `/home/ec2-user/environment`.

---

## 1. Commands used (in order)

### Task 1: Check the environment

| Command | Purpose |
|---|---|
| `pwd` | Show current directory (`/home/ec2-user/environment`) |
| `ls -la` | List files (security.yaml, template.yaml, troubleshooting/, .git). Note: I typed `la -la` once by mistake -> "command not found" |
| `git status` | Confirm clean git repo ("nothing to commit, working tree clean") |

### Task 2: Connect to Kiro

| Command | Purpose |
|---|---|
| `kiro-cli login --use-device-flow` | Log in with AWS Builder ID. Gives a code + URL to open in the browser |
| `kiro-cli` | Start the Kiro CLI chat |

### Task 3: Review and fix (prompts typed inside Kiro)

1. `Please review the security.yaml file in my current directory for security vulnerabilities and compliance issues.`
2. `Fix all the security vulnerabilities you identified in the security.yaml file. Update the file directly with the corrected code.`
   - When asked for write permission: choose **Trust, always allow in this session**, scope **Complete directory /home/ec2-user/environment**.
3. `Review the updated security.yaml file to confirm all security vulnerabilities have been fixed`

Lint check (in a second terminal, not inside Kiro):

| Command | Purpose |
|---|---|
| `cfn-lint security.yaml` | Validate the template |

Then I pasted the cfn-lint output into Kiro so it could fix the errors, and re-ran `cfn-lint security.yaml`. The second run returned no output, which means no issues.

Terminal tip: rename the Kiro terminal to `kiro` (right-click -> Rename) and keep a separate `bash` terminal for cfn-lint.

Source Control tip: use the Source Control panel in the IDE to see the git diff of what Kiro changed. Do **not** click Discard changes.

### Task 4: Go further (prompts inside Kiro)

1. `Check this template against AWS security best practices and compliance frameworks.`
2. `How can I prevent these types of security vulnerabilities in future CloudFormation templates?`

### Commands Kiro recommended for later (not run in the lab)

```bash
# Linting and scanning
pip install cfn-lint
cfn-lint security.yaml

gem install cfn-nag
cfn_nag_scan --input-path security.yaml

pip install checkov
checkov -f security.yaml --framework cloudformation

# Pre-commit hooks
pip install pre-commit
pre-commit install

# Account-wide EBS encryption by default
aws ec2 enable-ebs-encryption-by-default --region us-east-1
```

---

## 2. Step 1 findings: original template (12 issues)

### Critical
1. **Hardcoded AWS access key and secret key in EC2 UserData.** UserData is readable through the metadata service and console. Fix: use an IAM instance role, remove the credentials.
2. **Hardcoded password in UserData, written to a log file.** Fix: use Secrets Manager or SSM Parameter Store (SecureString) and fetch at runtime.

### High
3. **S3 public access block disabled** (all four flags false). Fix: set all four to `true`; if public reads are needed, use CloudFront with OAC.
4. **S3 bucket policy allows public read and write** (`Principal: '*'`, `s3:GetObject` + `s3:PutObject`). Fix: restrict principal to specific roles/services, remove `PutObject` from public policy.
5. **SSH (22) open to 0.0.0.0/0.** Fix: restrict CIDR (VPN/bastion) or use SSM Session Manager.
6. **RDP (3389) open to 0.0.0.0/0.** Same fix as SSH. RDP is a common ransomware entry point.

### Medium
7. **EBS root volume not encrypted.** Fix: `Encrypted: true`.
8. **EC2 detailed monitoring off** (5 min metrics instead of 1 min). Fix: `Monitoring: true`.
9. **Unrestricted egress** (`IpProtocol: -1` to 0.0.0.0/0). Fix: allow only needed ports/destinations.

### Low / compliance
10. **No S3 server-side encryption.** Fix: add `BucketEncryption` (aws:kms or AES256).
11. **No S3 versioning or access logging.** Fix: add `VersioningConfiguration` and `LoggingConfiguration`.
12. **No DeletionPolicy on the bucket.** Fix: `DeletionPolicy: Retain` (or Snapshot).

## 3. What Kiro changed

- Removed all keys/passwords from UserData; it now uses `aws secretsmanager get-secret-value` at runtime.
- Added `EC2InstanceRole` and `EC2InstanceProfile` with least-privilege policies plus `AmazonSSMManagedInstanceCore`.
- S3 public access block: all four flags `true` (both buckets).
- Bucket policy: principal is now the EC2 role ARN, `PutObject` removed, added a `DenyNonTLS` statement (HTTPS only).
- SSH/RDP ingress use new parameters `AllowedSSHCidr` / `AllowedRDPCidr` (default `10.0.0.0/8`).
- EBS `Encrypted: true`, `Monitoring: true`.
- Egress limited to TCP 443.
- Added `BucketEncryption` (aws:kms), versioning, access logging to a new `S3LoggingBucket`, `DeletionPolicy: Retain`.

---

## 4. cfn-lint results and fixes

First run:

```
W3011 Both 'UpdateReplacePolicy' and 'DeletionPolicy' are needed to protect resource from deletion
security.yaml:23:3
W3011 (same warning)
security.yaml:47:3
E3021 'VpcId' is a dependency of 'SecurityGroupEgress'
security.yaml:184:5
```

Fixes Kiro made:
- Added `UpdateReplacePolicy: Retain` to `S3LoggingBucket` and `S3Bucket`.
- Added a `VpcId` parameter (`Type: AWS::EC2::VPC::Id`) and `VpcId: !Ref VpcId` on `SecureSecurityGroup`.

Why it matters:
- `DeletionPolicy` only protects when the **stack is deleted**.
- `UpdateReplacePolicy` protects when CloudFormation **replaces** the resource during an update. You need both.
- Security group egress rules are VPC-scoped, so the group needs an explicit `VpcId`.

Second run of `cfn-lint security.yaml`: no output (clean).

---

## 5. Step 4: compliance review (recommendations still open)

Frameworks checked: AWS Well-Architected (Security), CIS AWS Foundations v2.0, NIST SP 800-53 Rev 5, PCI DSS v4.0, SOC 2 Type II.

| # | Gap | Severity | Recommendation |
|---|---|---|---|
| 1 | S3 uses aws:kms but no customer managed key (CMK) | Medium | Add an `AWS::KMS::Key`, set `KMSMasterKeyID`, enable `BucketKeyEnabled: true` |
| 2 | EBS encrypted but with default AWS-managed key | Medium | Add `KmsKeyId` pointing to a CMK |
| 3 | IMDSv2 not enforced on EC2 | Medium | `MetadataOptions: HttpTokens: required`, `HttpPutResponseHopLimit: 1` (protects against SSRF credential theft) |
| 4 | No CloudTrail / AWS Config rules | Medium | Enable CloudTrail; add Config rules like `ec2-imdsv2-check`, `s3-bucket-ssl-requests-only` |
| 5 | S3 Object Lock not enabled | Low | Use on the logging bucket for tamper-proof logs (PCI 10.5.1, NIST AU-9) |
| 6 | No MFA Delete on S3 | Low | CIS 2.1.2. Cannot be set in CloudFormation, needs an AWS CLI call after stack creation |
| 7 | CIDR parameters have no validation | Low | Add `AllowedPattern` (CIDR regex) and `ConstraintDescription` so `0.0.0.0/0` is not passed by accident |
| 8 | No lifecycle policy on logging bucket | Low | Add retention rule (PCI DSS needs about 1 year of logs) |

Other items the lab guide says Kiro may list: EC2 in default VPC (CIS 4.1), IAM role permissions boundary missing, missing tags, S3 lifecycle policy.

Priority per Kiro: IMDSv2 enforcement and customer managed KMS keys first.

Framework status summary:
- Well-Architected: strong (2 medium gaps: IMDSv2, CMK)
- CIS: mostly passing (MFA Delete, IMDSv2)
- NIST 800-53: mostly passing (CMK, Object Lock)
- PCI DSS: mostly passing (CMK, Object Lock, log retention)
- SOC 2: strong (log retention lifecycle)

---

## 6. How to prevent these issues in future templates

### 1. Lint and scan before commit
- **cfn-lint**: structure and best practice errors
- **cfn-nag**: security anti-patterns (open CIDRs, missing encryption, public buckets)
- **checkov**: maps findings to CIS/NIST/PCI/SOC 2

### 2. Git pre-commit hooks
- `cfn-lint` hook and **gitleaks** hook (blocks hardcoded secrets before they reach git)

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/aws-cloudformation/cfn-lint
    rev: v0.87.0
    hooks:
      - id: cfn-lint
        files: \.ya?ml$
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks
```

### 3. CI/CD gates
- Run cfn-lint, cfn-nag, checkov, gitleaks in the pipeline (e.g. GitHub Actions) with `soft_fail: false`.
- Make it a required status check so nothing deploys without passing.

### 4. AWS-side guardrails
- **AWS Config rules:** `s3-bucket-public-read-prohibited`, `s3-bucket-server-side-encryption-enabled`, `ec2-ebs-encryption-by-default`, `ec2-imdsv2-check`, `restricted-ssh`, `restricted-common-ports`
- **SCPs:** hard blocks at the organization level (e.g. deny turning off S3 public access block)
- **CloudFormation Guard (cfn-guard):** policy-as-code rules, e.g. `Properties.BucketEncryption exists` for every S3 bucket
- **EBS encryption by default** enabled account-wide

### 5. Secure baselines
- AWS CDK with **cdk-nag**
- Terraform registry modules with secure defaults
- **AWS Service Catalog** with approved, pre-scanned templates
- CloudFormation registry public extensions

### 6. Developer checklist (ask for every new resource)
- Does it store data? Is encryption on?
- Does it accept network traffic? Is the CIDR the minimum needed?
- Does the IAM entity need wildcards? Can it be scoped further?
- Are any secrets, passwords or keys inline (UserData, env vars, parameter defaults)?
- Does it need both `DeletionPolicy` and `UpdateReplacePolicy`?
- Is there logging, monitoring or an audit trail?

### Top three if short on time
1. cfn-nag + gitleaks as pre-commit hooks
2. Checkov as a blocking gate in CI/CD
3. SCPs + AWS Config as an account-level backstop

---

## 7. Quick takeaways

- Never put credentials in UserData. Use IAM roles and Secrets Manager.
- Block public S3 access by default and enforce HTTPS-only.
- Use `DeletionPolicy` **and** `UpdateReplacePolicy` on stateful resources.
- Prefer SSM Session Manager over opening SSH/RDP.
- Lint first, scan second, enforce in CI and at the account level.
- Iterate: paste linter output back into Kiro and re-run until clean.
