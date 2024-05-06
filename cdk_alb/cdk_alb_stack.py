import os.path

from aws_cdk.aws_s3_assets import Asset as S3asset

from aws_cdk import (
    Duration,
    Stack,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_elasticloadbalancingv2 as elbv2,
    aws_elasticloadbalancingv2_targets as targets,
    CfnTag,
    CfnParameter
    # aws_sqs as sqs,
)

from constructs import Construct

dirname = os.path.dirname(__file__)

class CdkAlbStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        #Parameters
        YourIP = CfnParameter(
            self, "YourIP", 
            type="String",
            description="Enter your IP address in CIDR notation. Example: \"100.22.33.250/32\"",
            default="76.17.205.87/32"
        )
                             
        # Create Key Pair
        # https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_ec2/CfnKeyPair.html
        cfn_key_pair = ec2.CfnKeyPair(
            self, "MyCfnKeyPair",
            key_name="cdk-ec2-key-pair",
            tags=[CfnTag(key="key", value="value")],
        )

        #Create VPC
        vpc = ec2.Vpc(
            self, "EngineeringVPC",
            vpc_name = "EngineeringVPC",
            availability_zones=["us-east-1b", "us-east-1c"],
            #max_azs=1,
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/18"),
            subnet_configuration=[ 
                          ec2.SubnetConfiguration(name="PublicSubnet1", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24),
                          ec2.SubnetConfiguration(name="PublicSubnet2", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24)     
            ]
        )    
        
        # Create Security Group
        WebserverSG = ec2.SecurityGroup(
            self, "WebserverSG", 
            security_group_name="WebserverSG",
            vpc=vpc,
            allow_all_outbound=True
        )
        
        # Create Security Group Ingress Rule
        WebserverSG.add_ingress_rule(
            ec2.Peer.ipv4(YourIP.value_as_string), 
            ec2.Port.tcp(22), "allow SSH access")
            
        WebserverSG.add_ingress_rule(
            ec2.Peer.ipv4("0.0.0.0/0"), 
            ec2.Port.tcp(80), 
            "Allow incoming requests on port 80")
        
        # Instance Role and SSM Managed Policy
        InstanceRole = iam.Role(
            self, "InstanceSSM", 
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com")
        )

        InstanceRole.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"))
        InstanceRole.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("AmazonS3FullAccess"))
    
        # Create an EC2 instance
        web1 = ec2.Instance(self, "web1", 
                            vpc=vpc,
                            instance_type=ec2.InstanceType("t2.micro"),
                            machine_image=ec2.AmazonLinuxImage(generation=ec2.AmazonLinuxGeneration.AMAZON_LINUX_2),
                            role=InstanceRole,
                            security_group=WebserverSG,
                            vpc_subnets=ec2.SubnetSelection(subnet_group_name="PublicSubnet1"),
                            key_name=cfn_key_pair.key_name
                          )
                            
        # Create an EC2 instance
        web2 = ec2.Instance(self, "web2", 
                            vpc=vpc,
                            instance_type=ec2.InstanceType("t2.micro"),
                            machine_image=ec2.AmazonLinuxImage(generation=ec2.AmazonLinuxGeneration.AMAZON_LINUX_2),
                            role=InstanceRole,
                            security_group=WebserverSG,
                            vpc_subnets=ec2.SubnetSelection(subnet_group_name="PublicSubnet2"),
                            key_name=cfn_key_pair.key_name
                            )                       
                            
        # Script in S3 as Asset
        webinitscriptasset = S3asset(
            self, "Asset", 
            path=os.path.join(dirname, "configure.sh")
        )
        
        asset_path = web1.user_data.add_s3_download_command(
            bucket=webinitscriptasset.bucket,
            bucket_key=webinitscriptasset.s3_object_key
        )
        
        asset_path2 = web2.user_data.add_s3_download_command(
            bucket=webinitscriptasset.bucket,
            bucket_key=webinitscriptasset.s3_object_key
        )

        # Userdata executes script from S3 for web1
        web1.user_data.add_execute_file_command( file_path=asset_path )
        webinitscriptasset.grant_read(web1.role)
        
        # Userdata executes script from S3 for web2
        web2.user_data.add_execute_file_command( file_path=asset_path2 )
        webinitscriptasset.grant_read(web2.role)             
        
        # Allow inbound HTTP traffic in security groups
        web1.connections.allow_from_any_ipv4(ec2.Port.tcp(80))
        web2.connections.allow_from_any_ipv4(ec2.Port.tcp(80))        
        
        #Create Load Balancer
        lb = elbv2.ApplicationLoadBalancer(
            self, "EngineeringLB",
            load_balancer_name="EngineeringLB",
            vpc=vpc,
            internet_facing=True,
            security_group=WebserverSG,
            vpc_subnets=ec2.SubnetSelection(one_per_az=True)
        )
        
        #Create Target Group
        target_groups= elbv2.ApplicationTargetGroup(
            self, "EngineeringWebservers",
            target_group_name="EngineeringWebservers",
            protocol=elbv2.ApplicationProtocol.HTTP,
            port=80,
            vpc=vpc,
            target_type=elbv2.TargetType.INSTANCE,
            targets=[ 
                targets.InstanceTarget(web1, 80), 
                targets.InstanceTarget(web2, 80)
            ],
            health_check=elbv2.HealthCheck(
                path="/ping",
                interval=Duration.minutes(1)
            )
        )
        
        # Add Listener
        listener = lb.add_listener(
            "Listener", 
            port=80, 
            open=True
        )
        
        listener.add_target_groups("http", target_groups=[target_groups])
