from setuptools import setup
import os
from glob import glob

package_name = 'mecanum_kinematics'

setup(
    name=package_name,
    version='0.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        
        # --- BURASI KRİTİK: Launch ve Parametre dosyalarını sisteme tanıtıyoruz ---
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'params'), glob('params/*.yaml')),
        # ------------------------------------------------------------------------
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='hasan',
    maintainer_email='hasan@todo.todo',
    description='Mecanum Kinematics Assignment',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            # DİKKAT: Satır sonunda VİRGÜL (,) olmak ZORUNDA
            'mecanum_kinematics_node = mecanum_kinematics.mecanum_kinematics_node:main',
            
            # İKİNCİ SATIR: Bu satır olmazsa gui_node oluşmaz
            'gui_node = mecanum_kinematics.mecanum_gui:main',
            'lidar_aligner = mecanum_kinematics.lidar_aligner:main',
            'llm_agent = mecanum_kinematics.llm_agent:main',
        ],
    },
)
