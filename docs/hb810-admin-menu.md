# HB810 admin menu and MCP coverage

This inventory comes from the admin panel in Helium on the 2degrees HB810 v1.0 in Router mode, firmware `0.5.0 3.0.0 v6095.0 Build 251128 Rel.64645n`. It covers the 9 Basic and 44 Advanced pages exposed by that configuration, plus the Quick Setup entry screen. The controls below are those visible when each page opened. Additional fields can appear after selecting a mode, enabling a feature, opening an edit form, or connecting hardware.

## MCP coverage

| Browser workflow | MCP path |
| --- | --- |
| Status, Network Map, Wi-Fi inventory, DHCP, and IPv6 | `router_status`, `list_clients`, `find_client`, `wifi_networks`, `dhcp_leases`, `dhcp_reservations`, and `ipv6_status` |
| Wireless Statistics | `list_clients` and `find_client` use the signal and link-rate tables behind Statistics and Network Map when a row matches the client MAC. `router_read` can inspect `DEV2_ADT_WIFI_CLIENT` and `DEV2_WIFI_APDEV_ASSOCDEV` directly. |
| System Log | `router_logs` reads the encrypted log. `router_read` can inspect `DEV2_SYSLOG_CFG`. |
| Firmware settings objects | `router_objects` lists objects and operations. `router_read` reads supported objects. `router_change` handles individual writes. `router_apply` previews and submits an ordered batch and reports the first failure and the steps already applied. |
| Wireless and address reservations | `set_wifi` selects an EX network by band and kind. `set_static_ip` and `remove_static_ip` use the EX reservation table. An add chooses the main DHCP pool when there is exactly one. |
| Diagnostics and EasyMesh | `start_diagnostic` starts a single ping, traceroute, or DNS lookup. `diagnostic_status` reads the current result. `start_mesh_pairing` and `mesh_pairing_status` cover push-button pairing. `manage_mesh_scan` and `mesh_scan_status` cover searching, refreshing, selecting a candidate by MAC, and returning the controller to idle. |
| Backup, restore, VPN, and local firmware | `export_router_file` saves a backup or OpenVPN client profile to a new file on the MCP server. `import_router_file` stages a local configuration or firmware image and sends the apply request only after the router acknowledges staging. Restore and upgrade may restart the router. |
| Guided and cloud workflows | The guided Quick Setup wizard, TP-Link Cloud sign-in, and online or satellite firmware upgrades still use the browser. |

Examples of objects confirmed against this router include `DEV2_ADT_WIFI_COMMON`, `DEV2_ADT_WAN`, `DEV2_ADT_LAN`, `DEV2_HOST_ENTRY`, `DEV2_DHCPV4_POOL_STATICADDR`, `DEV2_X_TP_EASYMESH`, `DEV2_FIREWALL`, `DEV2_HOST_ACCESSCONTROL`, `DEV2_PORTMAPPING`, and `DEV2_UPNP_CFG`. A catalog match is a candidate. The firmware can reject objects for a different model, mode, or feature.

The DHCP reservation editor uses `DEV2_DHCPV4_POOL_STATICADDR`. To choose among multiple pools, read `DEV2_DHCPV4_SERVER_POOL`, then use `router_change` with the selected main pool's `parent_stack` and the fields `chaddr`, `yiaddr`, and `enable`. Wi-Fi settings that apply across several bands can use `router_apply` with one step per radio. The router applies steps in order and provides no rollback if a later step fails.

The menu audit and hardware checks were read-only. An encrypted loopback simulator exercises the MCP stdio server, router login, settings changes, diagnostics, pairing, file transfers, and reboot. `TPLINK_WRITE=off` keeps these actions unavailable on the live MCP. [HB810 configuration](../README.md#quick-start)

## Quick Setup

The entry screen shows Region and Time Zone with Exit and Next. The wizard was inspected at its entry screen.

## Basic

| Page | Visible fields and options | Visible actions |
| --- | --- | --- |
| Network Map | ID, Device Name, IP Address, MAC Address, Connection Type, Signal Strength, Link Rate, Operation, Status, SSID, Channel, MAC, Band, LAN Port, Negotiation Speed | Add Mesh Device, Refresh |
| Internet | VLAN ID, Enable, VLAN ID ( 1 - 4094 ), Internet Connection Type, IP Address, Subnet Mask, Gateway | Save |
| Wireless | Band Steering, 6GHz Wireless Network, Enable, Network Name (SSID), Hide SSID, Password, MLO Network, Band | Save |
| Guest Network | See each other, Allow Guests to Access Each Other, 5GHz Wireless, Enable Guest Network | Save |
| Multi-SSID | MSSID1, Enable, MSSID2 | Save |
| USB Sharing / USB Storage Device | Volume Name, Total, Active, Operation, Network/Media Server Name, Share All, Enable Authentication, ID, Folder Name, Folder Path | Scan, Save, Refresh |
| Parental Controls | Name, Filter Level, Time Limits, Devices, Insights, Internet Access | Add, Modify |
| TP-Link Cloud | — | — |
| Mesh | Mesh, EasyMesh Controller, EasyMesh Agent | + Add Mesh Device, Reset to Agent |

## Advanced

| Page | Visible fields and options | Visible actions |
| --- | --- | --- |
| Status | WAN Interface Name, MAC Address, IP Address, Subnet Mask, Default Gateway, Primary DNS, Secondary DNS, Connection Type, Up Time, Network Name (SSID), Wireless Radio, Mode, Channel Width, Channel, DHCP | — |
| Operation Mode | Router(Current mode), Access Point | Save |
| Guest Network | See each other, Allow Guests to Access Each Other | Save |
| Parental Controls | Name, Filter Level, Time Limits, Devices, Insights, Internet Access | Add, Modify |
| QoS | QoS, Enable, Upload Bandwidth, IPTV QoS | Save, Add |
| Network / Internet | Default Gateway, DNS Lookup, IPv4 Ping, IPv6 Ping, Connection Name, Service Type, VLAN ID, Status, Operation, Enable | Save, Refresh, Add, Delete All, Modify |
| Network / LAN Settings | IP Address, Subnet Mask, DHCP Pool, Enable, Total Clients, ID, Client Name, MAC Address, Assigned IP, Leased Time, Reserved IP Address, Vendor ID, Starting IP Address/Ending IP Address, Facility, Status | Refresh, Modify, Add, Delete |
| Network / Dynamic DNS | Service Provider, TP-Link, Dyndns, NO-IP | — |
| Network / Static Routing | ID, Network Destination, Subnet Mask, Gateway, Enable | Add, Delete, Modify |
| Network / RIP Settings | MD5 Authentication, Enable, Interface, Version, AcceptRA, SendRA, Enabled, RipngEnabled | Save, Modify |
| Wireless / Wireless Settings | Band Steering, Wireless Radio, Enable, Network Name (SSID), Hide SSID, Security, Password, Transmit Power, Low, Middle, High | Save |
| Wireless / IoT Network | IoT Network, Enable | Save |
| Wireless / WPS | Enable Router's PIN, Router's PIN, Enable WPS, Push Button (Recommended), PIN Number | Generate, Default, Connect |
| Wireless / Wireless Schedule | Wireless Schedule | — |
| Wireless / Statistics | ID, Name, MAC Address, Connection Type, Security, Signal Strength, Received Packets, Sent Packets | Refresh |
| Wireless / Advanced Settings | Beacon Interval, RTS Threshold, DTIM Interval, Group Key Update Period, WMM, Enable, Short GI, AP Isolation | Save |
| Wireless / Multi-SSID | MSSID1, Enable, MSSID2 | Save |
| Wireless / Mesh | Mesh, EasyMesh Controller, EasyMesh Agent | + Add Mesh Device, Reset to Agent |
| NAT Forwarding / ALG | PPTP Pass-through, Enable, L2TP Pass-through, IPSec Pass-through, FTP ALG, TFTP ALG, H323 ALG, RTSP ALG, SIP ALG | Save |
| NAT Forwarding / Virtual Servers | ID, Service Type, External Port, Internal IP, Internal Port, Protocol, Status | Add, Delete, Modify |
| NAT Forwarding / Port Triggering | ID, Application, Triggering Port, Triggering Protocol, External Port, External Protocol, Status | Add, Delete, Modify |
| NAT Forwarding / DMZ | DMZ, Enable, DMZ Host IP Address | Save |
| NAT Forwarding / UPnP | UPnP, Total Clients, ID, Service Description, External Port, Protocol, Internal IP Address, Internal Port | Refresh |
| USB Sharing / USB Storage Device | Volume Name, Total, Active, Operation | Scan |
| USB Sharing / Sharing Access | Account, Use Default Account, Use New Account, Network/Media Server Name, Enable, Access Method, Access Address, Port, Share All, Enable Authentication, ID, Folder Name, Folder Path, Volume Name | Save, Refresh |
| Security / Firewall & DoS Protection | IPv4 SPI Firewall, IPv6 SPI Firewall, DoS Protection, ICMP-Flood Attack Filtering, UDP-Flood Attack Filtering, TCP-Flood Attack Filtering, Host Number: 0, ID, IP Address, MAC Address, ICMP-Flood Protection Level, Low, Middle, High, UDP-Flood Protection Level, TCP-SYN-Flood Protection Level | Save, Refresh, Delete |
| Security / Service Filtering | Service Filtering, ID, Service Type, Port, IP Address, Status | Refresh, Add, Delete, Modify |
| Security / Access Control | Access Control, Access Mode, Deny List, Allow List, ID, Device Name, MAC Address, IP Address, Connection Type | Save, Add, Delete, Modify, Refresh, Block |
| Security / IP & MAC Binding | IP & MAC Binding, ID, MAC Address, IP Address, Status, Enable, Device Name, Bound | Add, Delete, Modify, Refresh, Bind |
| Security / IPv6 Firewall | ID, Service Type, Internal IP, Internal Port, Protocol, Status | Add, Delete, Modify |
| VPN / OpenVPN | Enable VPN Server, Service Type, UDP, TCP, Service Port, VPN Subnet/Netmask, Client Access, Home Network Only, Internet and Home Network, Generate the certificate., Export the configuration. | Save, Generate, Export |
| VPN / PPTP VPN | Enable VPN Server, Client IP Address, Username, Password | Save |
| VPN / IPSec VPN | Dead Peer Detection, Connection Name, Remote Gateway, Local Address, Remote Address, Status, Enable | Add, Delete, Modify |
| VPN / VPN Connections | ID, Client IP Address, Connection Name, Remote Gateway, Local Address, Remote Address, Status, Enable | Modify |
| System Tools / Time Settings | Time Zone, Date, Time, NTP, Enable, NTP Server I, NTP Server II | Get from PC, Get from the Internet, Save |
| System Tools / LED Control | LED Enable, Night Mode, Enable, Night Mode Period, to | Save |
| System Tools / Diagnostics | Choose the test operation, Ping, Traceroute, Nslookup, IP address/Domain name | Start |
| System Tools / Firmware Upgrade | Firmware Version, Hardware Version, Auto Update, Current Time, Update Time, ID, Device Name, Model Name, MAC Address, Latest Firmware, New Firmware File | Upgrade, Check for Upgrades, Browse |
| System Tools / Backup & Restore | Protect the config file with a password, Enable, File, Enter the password of the config file | Backup, Browse, Restore, Factory Restore |
| System Tools / Reboot Schedule | Current Time, Reboot Schedule, Enable, Repeat, Reboot Time | Reboot, Save |
| System Tools / Administration | Old User Name, Old Password, New User Name, New Password, Confirm New Password, Port for HTTP, Local Management via HTTPS, Enable, Port for HTTPS, IP/MAC Address, Remote Management, Remote Management via HTTPS, Only the Following IP Addresses, Add a new IP, Add a new Range, All, HTTP Referer Head Check, ICMP Ping, Remote, Local, Update Session ID | Save, Download Certificate |
| System Tools / System Log | Type, Level, ID, Time, Log Content | Log Settings, Save Log, Refresh, Delete All |
| System Tools / Traffic Statistics | Enable Traffic Statistics, Statistics Interval, IP Address/ MAC Address, Total Packets, Total Bytes, Current Packets, Current Bytes, Current ICMP Tx, Current UDP Tx, Current SYN Tx | Save, Refresh, Reset, Delete All, Modify |
| System Tools / Port Mirror | Enable, LAN Interface, Timeout | Save |
