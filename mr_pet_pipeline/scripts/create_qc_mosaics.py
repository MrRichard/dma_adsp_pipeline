#!/usr/bin/env python

import argparse
import nibabel as nib
from nilearn import plotting
import matplotlib.pyplot as plt
import numpy as np

def create_qc_mosaic(base_image_path, overlay_image_path, output_path, title, off_center_sag=20):
    """
    Generates a mosaic of three views (Axial, Coronal, Sagittal) showing an
    overlay on a base anatomical image.

    Args:
        base_image_path (str): Path to the base anatomical image (e.g., T1w).
        overlay_image_path (str): Path to the overlay image (e.g., PET, GM mask).
        output_path (str): Path to save the output PNG image.
        title (str): Title for the plot.
        off_center_sag (int): Offset in mm from the center for the sagittal view.
    """
    try:
        # Load the base and overlay images
        base_img = nib.load(base_image_path)
        overlay_img = nib.load(overlay_image_path)

        # Create a figure
        fig, axes = plt.subplots(1, 3, figsize=(15, 5))
        fig.suptitle(title, fontsize=16, y=1.0)

        # Get the center coordinates for slicing
        center_coords = plotting.find_xyz_cut_coords(base_img)
        
        # Adjust for off-center sagittal
        sag_coord = center_coords[0] + off_center_sag

        # Default plot settings
        plot_args = {}
        
        # Customize plot settings based on title
        if "Registration" in title:
            plot_args['cmap'] = 'hot'
        elif "GM Segmentation" in title or "Cerebellum" in title:
            plot_args['cmap'] = 'Reds'
        
        # Add colorbar only for SUVR images
        plot_args['colorbar'] = "SUVR" in title


        # --- Create each plot individually ---
        
        # 1. Axial view
        plotting.plot_anat(
            anat_img=base_img,
            display_mode='z',
            cut_coords=[center_coords[2]],
            axes=axes[0],
            figure=fig,
        )
        plotting.plot_roi(
            roi_img=overlay_img,
            bg_img=base_img,
            display_mode='z',
            cut_coords=[center_coords[2]],
            axes=axes[0],
            figure=fig,
            **plot_args
        )
        axes[0].set_title('Axial')

        # 2. Coronal view
        plotting.plot_anat(
            anat_img=base_img,
            display_mode='y',
            cut_coords=[center_coords[1]],
            axes=axes[1],
            figure=fig,
        )
        plotting.plot_roi(
            roi_img=overlay_img,
            bg_img=base_img,
            display_mode='y',
            cut_coords=[center_coords[1]],
            axes=axes[1],
            figure=fig,
            **plot_args
        )
        axes[1].set_title('Coronal')

        # 3. Off-center Sagittal view
        plotting.plot_anat(
            anat_img=base_img,
            display_mode='x',
            cut_coords=[sag_coord],
            axes=axes[2],
            figure=fig,
        )
        plotting.plot_roi(
            roi_img=overlay_img,
            bg_img=base_img,
            display_mode='x',
            cut_coords=[sag_coord],
            axes=axes[2],
            figure=fig,
            **plot_args
        )
        axes[2].set_title(f'Sagittal (Offset: {off_center_sag}mm)')

        #plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close(fig)
        print(f"Successfully created QC mosaic: {output_path}")

    except Exception as e:
        print(f"Error creating QC mosaic for {overlay_image_path} on {base_image_path}: {e}")

def create_label_qc_mosaic(base_image_path, overlay_image_path, output_path, title, off_center_sag=20):
    """
    Generates a mosaic of three views (Axial, Coronal, Sagittal) showing a
    label overlay on a base anatomical image.

    Args:
        base_image_path (str): Path to the base anatomical image (e.g., T1w).
        overlay_image_path (str): Path to the label image (e.g., atlas).
        output_path (str): Path to save the output PNG image.
        title (str): Title for the plot.
        off_center_sag (int): Offset in mm from the center for the sagittal view.
    """
    try:
        # Load the base and overlay images
        base_img = nib.load(base_image_path)
        overlay_img_orig = nib.load(overlay_image_path)

        # Set 0 label to NaN to make it transparent
        overlay_data = overlay_img_orig.get_fdata()
        overlay_data[overlay_data == 0] = np.nan
        overlay_img = nib.Nifti1Image(overlay_data, overlay_img_orig.affine)

        # Create a figure
        fig, axes = plt.subplots(1, 3, figsize=(15, 5))
        fig.suptitle(title, fontsize=16, y=1.0)

        # Get the center coordinates for slicing
        center_coords = plotting.find_xyz_cut_coords(base_img)
        
        # Adjust for off-center sagittal
        sag_coord = center_coords[0] + off_center_sag

        # --- Create each plot individually ---
        
        # 1. Axial view
        plotting.plot_stat_map(
            stat_map_img=overlay_img,
            bg_img=base_img,
            display_mode='z',
            cut_coords=[center_coords[2]],
            axes=axes[0],
            figure=fig,
            colorbar=False,
            #cmap='Paired',
            transparency=0.5
        )
        axes[0].set_title('Axial')

        # 2. Coronal view
        plotting.plot_stat_map(
            stat_map_img=overlay_img,
            bg_img=base_img,
            display_mode='y',
            cut_coords=[center_coords[1]],
            axes=axes[1],
            figure=fig,
            colorbar=False,
            #cmap='Paired',
            transparency=0.5
        )
        axes[1].set_title('Coronal')

        # 3. Off-center Sagittal view
        plotting.plot_stat_map(
            stat_map_img=overlay_img,
            bg_img=base_img,
            display_mode='x',
            cut_coords=[sag_coord],
            axes=axes[2],
            figure=fig,
            colorbar=False,
            #cmap='Paired',
            transparency=0.5
        )
        axes[2].set_title(f'Sagittal (Offset: {off_center_sag}mm)')

        #plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close(fig)
        print(f"Successfully created QC mosaic: {output_path}")

    except Exception as e:
        print(f"Error creating label QC mosaic for {overlay_image_path} on {base_image_path}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Generate QC mosaic images for neuroimaging data.")
    parser.add_argument("--base", required=True, help="Path to the base anatomical image (NIfTI or MGZ).")
    parser.add_argument("--overlay", required=True, help="Path to the overlay image (NIfTI or MGZ).")
    parser.add_argument("--output", required=True, help="Path to save the output PNG image.")
    parser.add_argument("--title", default="QC Overlay", help="Title for the plot.")
    parser.add_argument("--sag-offset", type=int, default=20, help="Offset in mm for the sagittal view from the center.")
    parser.add_argument("--mode", default="roi", choices=["roi", "label"], help="Type of overlay to plot.")

    args = parser.parse_args()

    if args.mode == "label":
        create_label_qc_mosaic(args.base, args.overlay, args.output, args.title, args.sag_offset)
    else:
        create_qc_mosaic(args.base, args.overlay, args.output, args.title, args.sag_offset)

if __name__ == "__main__":
    main()