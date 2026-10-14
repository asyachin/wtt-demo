# 0010 — Do Not Use Ansible

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-14 |
| Deciders | Alexander Syachin |
| Block | 00 |
| Supersedes | none |
| Superseded by | none |

## Context

The job advertisement lists Ansible, and the first version of this project's README listed it in the technology stack.

The architecture is AWS EKS with Terraform, Helm, and Argo CD. Looking at what is actually left for a configuration management tool to do:

| Layer | Managed by |
|---|---|
| AWS resources | Terraform |
| Node operating system | Amazon Linux 2023, from an AWS-managed AMI, replaced rather than patched |
| Cluster add-ons | Terraform, through the Helm provider |
| Application configuration | Helm values, in Git |
| Delivery and drift correction | Argo CD |
| Secrets | External Secrets Operator |

There is no host to configure. Nodes are immutable and are replaced by the node group, not updated in place. There is no bastion, no virtual machine running an application, and no legacy server.

## Options Considered

| Option | Advantage | Disadvantage |
|---|---|---|
| Omit Ansible, and record why | Honest. No unused code. The reasoning itself demonstrates the judgement the role needs. | A reviewer scanning for the keyword does not find it |
| Write a playbook for a narrow real task, such as bootstrapping a bastion host | Ansible appears, and does something | It would need a bastion that nothing else requires, so a component is added to the architecture in order to justify a tool. Backwards. |
| Write a playbook that wraps `terraform apply` and `helm upgrade` | Ansible appears immediately | A wrapper around two tools that are already declarative. It adds a layer, hides the real commands, and would be visible as padding to any reviewer who reads it. |
| Use Ansible instead of Terraform for AWS | Ansible does real work | Its AWS modules are weaker than Terraform for this, there is no plan step, and no state file. A worse platform in order to use a listed tool. |

## Decision

Ansible is not used. It is removed from the README. This record is the explanation.

## Reasoning

A tool is chosen because it solves a problem that exists. On this architecture, Ansible has no problem to solve: Terraform owns the infrastructure, Helm and Argo CD own the workloads, and the nodes are immutable.

Adding a playbook anyway would produce one of three things, and all three are worse than omitting it. A wrapper around `terraform apply` adds a layer that hides the real command. A bastion host added so that there is something to configure means inventing a component to justify a tool. A node hardening playbook run against immutable nodes fights the node group, which replaces the node and loses the change.

Any engineer reviewing the repository would see which of those it was within a minute. A short, reasoned record of why the tool was left out demonstrates more engineering judgement than a playbook that exists for the keyword, and it also answers the question directly if it comes up in an interview.

The skill is not hidden by this. Ansible experience belongs on a curriculum vitae and in a conversation. A repository is for the architecture that was actually chosen.

There is also a correctness argument. Mutable configuration applied to immutable nodes creates drift between the AMI and the running state, which is exactly the class of problem that immutable infrastructure exists to remove. Introducing it to satisfy a keyword would be a regression.

## Consequences

### Positive

- No unused code, no playbook to maintain, no second configuration system.
- A clear boundary: Terraform for infrastructure, Helm and Argo CD for workloads, nothing in between.
- The decision and its reasoning are available if a reviewer asks about Ansible.
- Nodes stay immutable, so a node is always a known quantity.

### Negative

- A reviewer searching the repository for Ansible does not find it, and may read that as a gap rather than a choice. This record and the "out of scope" table in `docs/about.md` are the mitigation, and they only work if the reviewer reads them.
- If a later requirement needs host-level configuration, it has to be introduced from nothing rather than extended.

### Neutral

- Node operating system updates are handled by replacing the node group's AMI version in Terraform and letting the nodes roll, which is a different operational model from patching with Ansible and is written into the runbook.

## Verification

- `git grep -i ansible` finds matches only in this record and in the "out of scope" table in `docs/about.md`.
- `docs/about.md` lists Ansible under what is not included, with a reason and a link here.
- No file under `infra/` is a playbook, an inventory, or a role.

## Revisit When

The platform has to manage something that is not a container and not an AWS resource: a self-managed Kubernetes control plane on virtual machines, a physical host, or a legacy application server. Any of those makes Ansible the right tool, and this record is superseded rather than edited.
