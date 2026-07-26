# The measurement environment, and nothing else.
#
# Fixtures never live in image layers -- they are bind-mounted at run time.
# Baking one in would put the dataset under overlayfs, which is a filesystem
# the suite has no interest in measuring and cannot vary as an axis.
#
# The base image is deliberately NOT pinned by digest here. Pinning specs is
# purity over practicality (the same call made for con-duct); the contract is
# that the resolved digest is captured per-record, where it can be compared
# across arms rather than merely asserted.

FROM python:3.13-slim

# git is the thing under test's only hard system dependency. ca-certificates so
# pip and any clone can reach the network.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Everything above this line is the base: the measurement floor, identical
# across every arm being compared. Everything below is the environment under
# test. When a second arm appears, the split happens exactly here -- this file
# keeps the base, and each environment becomes `FROM ladometer-base` plus the
# one line below.
#
# git-annex is a package like any other (psychoinformatics-de/git-annex-wheel),
# so the environment pins the annex version instead of inheriting the host's --
# same rationale as environments.py.
RUN pip install --no-cache-dir \
      datalad==1.6.1 \
      git-annex \
      con-duct
