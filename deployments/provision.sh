#!/usr/bin/env bash
# One-time AWS provisioning with the AWS CLI's configured profile. Idempotent (looks up by name).
# Creates: key pair iema-prod, security group iema-prod-sg (22 from SSH_CIDR, 80, 443),
#          1x EC2 t3.large Ubuntu 24.04 (40GB gp3) tagged Name=iema-prod, 1x Elastic IP.
# Env overrides: AWS_PROFILE AWS_REGION INSTANCE_TYPE SSH_CIDR KEY_FILE
set -euo pipefail
cd "$(dirname "$0")"
NAME=iema-prod
REGION=${AWS_REGION:-$(aws configure get region || echo ap-south-1)}
export AWS_DEFAULT_REGION=$REGION
TYPE=${INSTANCE_TYPE:-t3.large}
KEY_FILE=${KEY_FILE:-$HOME/.ssh/$NAME.pem}
SSH_CIDR=${SSH_CIDR:-$(curl -fsS https://checkip.amazonaws.com | tr -d '\n')/32}

aws sts get-caller-identity --query Arn --output text
echo "region=$REGION type=$TYPE ssh_cidr=$SSH_CIDR"

# key pair
if ! aws ec2 describe-key-pairs --key-names $NAME >/dev/null 2>&1; then
  aws ec2 create-key-pair --key-name $NAME --query KeyMaterial --output text > "$KEY_FILE"
  chmod 600 "$KEY_FILE"; echo "created key pair $NAME -> $KEY_FILE"
fi

# security group in the default VPC
VPC=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values=$NAME-sg Name=vpc-id,Values=$VPC --query 'SecurityGroups[0].GroupId' --output text)
if [ "$SG" = "None" ]; then
  SG=$(aws ec2 create-security-group --group-name $NAME-sg --description "iema prod web" --vpc-id $VPC --query GroupId --output text)
  aws ec2 authorize-security-group-ingress --group-id $SG --ip-permissions \
    "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=$SSH_CIDR,Description=ssh}]" \
    "IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0}]" \
    "IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}]" \
    "IpProtocol=udp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}]" >/dev/null
  echo "created security group $SG"
fi

# instance
IID=$(aws ec2 describe-instances --filters Name=tag:Name,Values=$NAME Name=instance-state-name,Values=pending,running,stopped \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
if [ "$IID" = "None" ]; then
  AMI=$(aws ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id --query Parameter.Value --output text)
  IID=$(aws ec2 run-instances --image-id $AMI --instance-type $TYPE --key-name $NAME --security-group-ids $SG \
    --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=40,VolumeType=gp3}' \
    --metadata-options HttpTokens=required \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME}]" "ResourceType=volume,Tags=[{Key=Name,Value=$NAME}]" \
    --query 'Instances[0].InstanceId' --output text)
  echo "created instance $IID"
fi
aws ec2 wait instance-running --instance-ids $IID

# elastic IP
IP=$(aws ec2 describe-addresses --filters Name=tag:Name,Values=$NAME --query 'Addresses[0].PublicIp' --output text)
if [ "$IP" = "None" ]; then
  ALLOC=$(aws ec2 allocate-address --domain vpc --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$NAME}]" --query AllocationId --output text)
  aws ec2 associate-address --instance-id $IID --allocation-id $ALLOC >/dev/null
  IP=$(aws ec2 describe-addresses --allocation-ids $ALLOC --query 'Addresses[0].PublicIp' --output text)
  echo "created elastic ip $IP"
fi

printf 'HOST=%s\nKEY_FILE=%s\nINSTANCE_ID=%s\nSG=%s\nREGION=%s\n' "$IP" "$KEY_FILE" "$IID" "$SG" "$REGION" > .deploy-state
echo "Elastic IP: $IP   -> point DNS A records iema.ai and www.iema.ai here."
echo "Wrote deployments/.deploy-state. Next: ./deploy.sh"
