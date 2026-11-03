!    Copyright (C) 2012 The SPEED FOUNDATION
!    Author: Ilario Mazzieri
!
!    This file is part of SPEED.
!
!    SPEED is free software; you can redistribute it and/or modify it
!    under the terms of the GNU Affero General Public License as
!    published by the Free Software Foundation, either version 3 of the
!    License, or (at your option) any later version.
!
!    SPEED is distributed in the hope that it will be useful, but
!    WITHOUT ANY WARRANTY; without even the implied warranty of
!    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
!    Affero General Public License for more details.
!
!    You should have received a copy of the GNU Affero General Public License
!    along with SPEED.  If not, see <http://www.gnu.org/licenses/>.

!> @brief Field output for ParaView (VTKWRITE T n), drop-in replacement of the original
!!        WRITE_VTU_TIMEDATA.f90 (same subroutines, same arguments: nothing else in SPEED changes).
!!
!! Three formats, chosen in SPEED.input on the VTKWRITE line (the original SPEED ignores the extra words):
!!   VTKWRITE  T 100              XDMF with strain (default)
!!   VTKWRITE  T 100 XDMF         VTKOUT/SPEED.xmf + SPEED_elements.xmf + raw binary files. Same data as the original
!!                                (all GLL nodes, same node order, Disp and Strain, time = step * dt), but the mesh is
!!                                written once (mesh_points.bin, mesh_cells.bin, mesh_elements.bin) and each snapshot
!!                                only holds the fields (Disp_<step>.bin float32 (np,3), Strain_<step>.bin (np,6)).
!!                                SPEED.xmf: each spectral element as (nn-1)^3 linear hexahedra through its GLL nodes
!!                                (ParaView's XDMF reader has no reliable Lagrange hexahedron);
!!                                SPEED_elements.xmf: the spectral elements (8 corners), the grid of the mesh file.
!!   VTKWRITE  T 100 VTUBINARY    exactly the files of the original (.vtu / .pvtu / .pvd, Lagrange cells), binary.
!!   VTKWRITE  T 100 VTUASCII     the original text files.
!!   ... NOSTRAIN                 leaves the strain out (e.g. VTKWRITE T 100 XDMF NOSTRAIN).
!! If the line has no format word, the environment variables SPEED_VTK_FORMAT (xdmf / binary / ascii) and
!! SPEED_VTK_STRAIN (0 / 1) are used; SPEED.input wins over them.
!! Fix: the original clamped the strain with "if (strain < 1e-29) strain = 1e-29", which turned every
!! negative strain into +1e-29; now only the magnitude is limited to the float32 range.
!!
!! Original version: Srihari Sangaraju, July 2021. Binary and XDMF output: 2026.

module speed_vtk_out
    implicit none
    integer, save :: vtk_mode = -1            ! 0 ascii, 1 binary vtu, 2 xdmf + binary
    logical, save :: vtk_strain = .false.
    real*8,  save :: vtk_dt = 0.d0            ! from WRITE_PVD_TIMEDATA (rank 0, called at its = 0)
    logical, save :: vtk_mesh_done = .false.  ! xdmf: mesh written
    integer, save :: vtk_np_tot = 0           ! xdmf: points of all partitions
    integer, save :: vtk_nc_tot = 0           ! xdmf: linear hexahedra of all partitions
    integer, save :: vtk_ne_tot = 0           ! xdmf: spectral elements of all partitions
    integer(kind=8), save :: vtk_xmf_pos = 0  ! xdmf: byte position of the closing tags in SPEED.xmf
    integer(kind=8), save :: vtk_xme_pos = 0  ! xdmf: same in SPEED_elements.xmf
    logical, save :: vtk_bcast_done = .false.  ! format sent from rank 0 to all ranks

contains

    subroutine vtk_settings()
        ! 1. words after "VTKWRITE T n" in SPEED.input: XDMF | VTUBINARY | VTUASCII, and NOSTRAIN | STRAIN
        ! 2. if SPEED.input says nothing: the environment (SPEED_VTK_FORMAT, SPEED_VTK_STRAIN)
        ! 3. else XDMF with strain
        character(len=32) :: s
        integer :: l, st, fmode, fstrain
        if (vtk_mode .ge. 0) return
        vtk_mode = 2
        vtk_strain = .true.                             ! as the original: strain and displacement
        call get_environment_variable('SPEED_VTK_FORMAT', s, l, st)
        if (st .eq. 0 .and. l .gt. 0) then
            select case (s(1:1))
            case ('a', 'A')
                vtk_mode = 0
            case ('b', 'B', 'v', 'V')
                vtk_mode = 1
            case ('x', 'X')
                vtk_mode = 2
            end select
        endif
        call get_environment_variable('SPEED_VTK_STRAIN', s, l, st)
        if (st .eq. 0 .and. l .gt. 0) vtk_strain = index('1yYtT', s(1:1)) .gt. 0
        call vtk_read_input(fmode, fstrain)
        if (fmode .ge. 0) vtk_mode = fmode
        if (fstrain .ge. 0) vtk_strain = (fstrain .eq. 1)
    end subroutine vtk_settings

    !> format words on the VTKWRITE line of SPEED.input, e.g.  "VTKWRITE  T 100 XDMF NOSTRAIN".
    !! SPEED itself reads only "T 100" from this line (list-directed read), so the original SPEED
    !! ignores the extra words and the same SPEED.input works with both versions.
    subroutine vtk_read_input(fmode, fstrain)
        integer, intent(out) :: fmode, fstrain
        character(len=512) :: line, up
        integer :: u, ios, i, j, n, m
        fmode = -1
        fstrain = -1
        open(newunit=u, file='SPEED.input', status='old', action='read', iostat=ios)
        if (ios .ne. 0) return
        do
            read(u, '(a)', iostat=ios) line
            if (ios .ne. 0) exit
            up = vtk_upper(adjustl(line))
            if (up(1:8) .ne. 'VTKWRITE') cycle
            m = len_trim(up)
            i = 1
            n = 0
            do while (i .le. m)
                if (vtk_blank(up(i:i))) then
                    i = i + 1
                    cycle
                endif
                j = i
                do while (j .le. m)
                    if (vtk_blank(up(j:j))) exit
                    j = j + 1
                enddo
                n = n + 1                                ! word n: VTKWRITE, T, n, then the options
                if (n .gt. 3) then
                    select case (up(i:j-1))
                    case ('XDMF')
                        fmode = 2
                    case ('VTUBINARY')
                        fmode = 1
                    case ('VTUASCII')
                        fmode = 0
                    case ('NOSTRAIN')
                        fstrain = 0
                    case ('STRAIN')
                        fstrain = 1
                    case default
                        write(*,'(A)') 'VTK: unknown word on the VTKWRITE line: '//up(i:j-1)// &
                                       ' (use XDMF, VTUBINARY, VTUASCII, NOSTRAIN)'
                    end select
                endif
                i = j
            enddo
        enddo
        close(u)
    end subroutine vtk_read_input

    logical function vtk_blank(c)
        character(len=1), intent(in) :: c
        vtk_blank = (c .eq. ' ' .or. c .eq. char(9) .or. c .eq. char(13))
    end function vtk_blank

    function vtk_upper(s) result(t)
        character(len=*), intent(in) :: s
        character(len=len(s)) :: t
        integer :: i, k
        t = s
        do i = 1, len(s)
            k = iachar(s(i:i))
            if (k .ge. 97 .and. k .le. 122) t(i:i) = achar(k - 32)
        enddo
    end function vtk_upper

    function i2s(i) result(s)
        integer(kind=8), intent(in) :: i
        character(len=24) :: s
        write(s, '(i0)') i
    end function i2s

    !> double -> float32 without overflow (|x| <= 1e30; tiny values become 0 by the conversion)
    elemental function to_f32(x) result(y)
        real*8, intent(in) :: x
        real*4 :: y
        y = real(max(-1.d30, min(1.d30, x)), 4)
    end function to_f32

end module speed_vtk_out


    subroutine  WRITE_VTU_TIMEDATA(nn_loc, cs_nnz_loc, cs_loc, &
                                  nmat, sdeg, prop_mat, tag_mat, &
                                  xx_loc, yy_loc, zz_loc, mpi_id, nmpi, &
                                  nn, vtk_numbering_map, &
                                  its, strain, stress, disp )
      use speed_vtk_out
      implicit none
      include 'SPEED.MPI'

      integer*4 :: nn_loc, cs_nnz_loc, mpi_id, nmat, nn, its, nmpi
      integer*4, dimension(nmat) :: sdeg, tag_mat
      integer*4, dimension(nn*nn*nn) :: vtk_numbering_map
      integer*4, dimension(0:cs_nnz_loc) :: cs_loc
      real*8, dimension(nmat,4) :: prop_mat
      real*8, dimension(nn_loc) :: xx_loc, yy_loc, zz_loc
      real*8, dimension(6*nn_loc) :: strain, stress
      real*8, dimension(3*nn_loc) :: disp
      integer*4 :: ierr

      if (.not. vtk_bcast_done) then
          ! rank 0 may already have decided in WRITE_PVD_TIMEDATA: every rank comes here once, together
          call vtk_settings()
          call MPI_BCAST(vtk_mode, 1, MPI_INTEGER, 0, SPEED_COMM, ierr)      ! same choice on every rank
          call MPI_BCAST(vtk_strain, 1, MPI_LOGICAL, 0, SPEED_COMM, ierr)
          vtk_bcast_done = .true.
          if (mpi_id .eq. 0) then
              select case (vtk_mode)
              case (0)
                  write(*,'(A)') 'VTK output: ascii .vtu (original format)'
              case (1)
                  write(*,'(A)') 'VTK output: binary .vtu'
              case (2)
                  write(*,'(A)') 'VTK output: VTKOUT/SPEED.xmf + binary files (mesh once, displacement per snapshot)'
              end select
              if (vtk_strain) write(*,'(A)') 'VTK output: with strain'
          endif
      endif

      select case (vtk_mode)
      case (0)
          call VTK_WRITE_ASCII(nn_loc, cs_nnz_loc, cs_loc, xx_loc, yy_loc, zz_loc, mpi_id, nmpi, &
                               nn, vtk_numbering_map, its, strain, disp)
      case (1)
          call VTK_WRITE_BINARY(nn_loc, cs_nnz_loc, cs_loc, xx_loc, yy_loc, zz_loc, mpi_id, nmpi, &
                                nn, vtk_numbering_map, its, strain, disp)
      case (2)
          call VTK_WRITE_XDMF(nn_loc, cs_nnz_loc, cs_loc, xx_loc, yy_loc, zz_loc, mpi_id, nmpi, &
                              nn, its, strain, disp)
      end select

    end subroutine WRITE_VTU_TIMEDATA


    !-----------------------------------------------------------------------------------------------
    !> connectivity of the local elements in VTK_LAGRANGE_HEXAHEDRON order, 0-based local node ids
    subroutine VTK_LOCAL_CONNECTIVITY(cs_nnz_loc, cs_loc, nn, vtk_numbering_map, nel_loc, conn)
      implicit none
      integer*4, intent(in) :: cs_nnz_loc, nn, nel_loc
      integer*4, dimension(0:cs_nnz_loc), intent(in) :: cs_loc
      integer*4, dimension(nn*nn*nn), intent(in) :: vtk_numbering_map
      integer*4, dimension(nn*nn*nn*nel_loc), intent(out) :: conn
      integer*4 :: ie, i, n3
      n3 = nn*nn*nn
      do ie = 1, nel_loc
          do i = 1, n3
              conn((ie-1)*n3 + i) = cs_loc(cs_loc(ie-1) + vtk_numbering_map(i)) - 1
          enddo
      enddo
    end subroutine VTK_LOCAL_CONNECTIVITY


    !-----------------------------------------------------------------------------------------------
    !> binary .vtu (appended raw data, UInt64 headers) + .pvtu; the .pvd is written by WRITE_PVD_TIMEDATA
    subroutine VTK_WRITE_BINARY(nn_loc, cs_nnz_loc, cs_loc, xx_loc, yy_loc, zz_loc, mpi_id, nmpi, &
                                nn, vtk_numbering_map, its, strain, disp)
      use speed_vtk_out
      implicit none
      integer*4, intent(in) :: nn_loc, cs_nnz_loc, mpi_id, nmpi, nn, its
      integer*4, dimension(0:cs_nnz_loc), intent(in) :: cs_loc
      integer*4, dimension(nn*nn*nn), intent(in) :: vtk_numbering_map
      real*8, dimension(nn_loc), intent(in) :: xx_loc, yy_loc, zz_loc
      real*8, dimension(6*nn_loc), intent(in) :: strain
      real*8, dimension(3*nn_loc), intent(in) :: disp

      character(len=80) :: fname
      character(len=1), parameter :: nl = char(10)
      integer :: u, i, ie, n3, nel_loc
      integer(kind=8) :: np8, ne8, off, b_pts, b_conn, b_off, b_typ, b_disp, b_str
      real*4, allocatable :: f3(:), f6(:)
      integer*4, allocatable :: conn(:), offs(:), typ(:)

      nel_loc = cs_loc(0) - 1
      n3 = nn*nn*nn
      np8 = nn_loc
      ne8 = nel_loc
      b_pts = 12_8*np8
      b_conn = 4_8*n3*ne8
      b_off = 4_8*ne8
      b_typ = 4_8*ne8
      b_disp = 12_8*np8
      b_str = 24_8*np8

      write(fname,'(a,i8.8,a,i5.5,a)') './VTKOUT/SNAPSHOT_', its, '.', mpi_id, '.vtu'
      open(newunit=u, file=trim(fname), access='stream', form='unformatted', status='replace', action='write')
      write(u) '<?xml version="1.0"?>'//nl
      write(u) '<VTKFile type="UnstructuredGrid" version="1.0" byte_order="LittleEndian" header_type="UInt64">'//nl
      write(u) '<UnstructuredGrid>'//nl
      write(u) '<Piece NumberOfPoints="'//trim(i2s(np8))//'" NumberOfCells="'//trim(i2s(ne8))//'">'//nl
      off = 0
      write(u) '<Points>'//nl
      write(u) '<DataArray type="Float32" NumberOfComponents="3" format="appended" offset="'//trim(i2s(off))//'"/>'//nl
      write(u) '</Points>'//nl
      off = off + 8 + b_pts
      write(u) '<Cells>'//nl
      write(u) '<DataArray type="Int32" Name="connectivity" format="appended" offset="'//trim(i2s(off))//'"/>'//nl
      off = off + 8 + b_conn
      write(u) '<DataArray type="Int32" Name="offsets" format="appended" offset="'//trim(i2s(off))//'"/>'//nl
      off = off + 8 + b_off
      write(u) '<DataArray type="Int32" Name="types" format="appended" offset="'//trim(i2s(off))//'"/>'//nl
      off = off + 8 + b_typ
      write(u) '</Cells>'//nl
      write(u) '<PointData>'//nl                          ! as the original: Strain, then Disp
      if (vtk_strain) then
          write(u) '<DataArray type="Float32" NumberOfComponents="6" Name="Strain" format="appended" offset="'// &
                   trim(i2s(off))//'"/>'//nl
          off = off + 8 + b_str
      endif
      write(u) '<DataArray type="Float32" NumberOfComponents="3" Name="Disp" format="appended" offset="'// &
               trim(i2s(off))//'"/>'//nl
      write(u) '</PointData>'//nl
      write(u) '</Piece>'//nl
      write(u) '</UnstructuredGrid>'//nl
      write(u) '<AppendedData encoding="raw">'//nl
      write(u) '_'

      allocate(f3(3*nn_loc))
      do i = 1, nn_loc
          f3(3*i-2) = to_f32(xx_loc(i))
          f3(3*i-1) = to_f32(yy_loc(i))
          f3(3*i)   = to_f32(zz_loc(i))
      enddo
      write(u) b_pts
      write(u) f3

      allocate(conn(n3*nel_loc), offs(nel_loc), typ(nel_loc))
      call VTK_LOCAL_CONNECTIVITY(cs_nnz_loc, cs_loc, nn, vtk_numbering_map, nel_loc, conn)
      do ie = 1, nel_loc
          offs(ie) = ie*n3
      enddo
      typ = 72                                        ! VTK_LAGRANGE_HEXAHEDRON
      write(u) b_conn
      write(u) conn
      write(u) b_off
      write(u) offs
      write(u) b_typ
      write(u) typ
      deallocate(conn, offs, typ)

      if (vtk_strain) then
          allocate(f6(6*nn_loc))
          f6 = to_f32(strain)
          write(u) b_str
          write(u) f6
          deallocate(f6)
      endif
      f3 = to_f32(disp)
      write(u) b_disp
      write(u) f3
      deallocate(f3)
      write(u) nl//'</AppendedData>'//nl//'</VTKFile>'//nl
      close(u)

      if (mpi_id .eq. 0) call VTK_WRITE_PVTU(nmpi, its, .true.)

    end subroutine VTK_WRITE_BINARY


    !-----------------------------------------------------------------------------------------------
    !> .pvtu of one snapshot (rank 0): lists the pieces SNAPSHOT_its.<rank>.vtu
    subroutine VTK_WRITE_PVTU(nmpi, its, binary)
      use speed_vtk_out
      implicit none
      integer*4, intent(in) :: nmpi, its
      logical, intent(in) :: binary
      character(len=80) :: fname, piece
      integer :: u, i

      write(fname,'(a,i8.8,a)') './VTKOUT/SNAPSHOT_', its, '.pvtu'
      open(newunit=u, file=trim(fname), status='replace', action='write')
      write(u,'(a)') '<?xml version="1.0" encoding="utf-8"?>'
      if (binary) then
          write(u,'(a)') '<VTKFile type="PUnstructuredGrid" version="1.0" byte_order="LittleEndian" header_type="UInt64">'
      else
          write(u,'(a)') '<VTKFile type="PUnstructuredGrid" version="0.1" byte_order="LittleEndian">'
      endif
      write(u,'(a)') '<PUnstructuredGrid GhostLevel="0">'
      write(u,'(a)') '<PPoints>'
      write(u,'(a)') '<PDataArray type="Float32" NumberOfComponents="3"/>'
      write(u,'(a)') '</PPoints>'
      write(u,'(a)') '<PCells>'
      write(u,'(a)') '<PDataArray type="Int32" Name="connectivity" NumberOfComponents="1"/>'
      write(u,'(a)') '<PDataArray type="Int32" Name="offsets" NumberOfComponents="1"/>'
      write(u,'(a)') '<PDataArray type="Int32" Name="types" NumberOfComponents="1"/>'
      write(u,'(a)') '</PCells>'
      write(u,'(a)') '<PPointData>'
      if (vtk_strain) write(u,'(a)') '<PDataArray type="Float32" NumberOfComponents="6" Name="Strain"/>'
      write(u,'(a)') '<PDataArray type="Float32" NumberOfComponents="3" Name="Disp"/>'
      write(u,'(a)') '</PPointData>'
      do i = 0, nmpi-1
          write(piece,'(a,i8.8,a,i5.5,a)') './SNAPSHOT_', its, '.', i, '.vtu'
          write(u,'(a)') '<Piece Source="'//trim(piece)//'"/>'
      enddo
      write(u,'(a)') '</PUnstructuredGrid>'
      write(u,'(a)') '</VTKFile>'
      close(u)
    end subroutine VTK_WRITE_PVTU


    !-----------------------------------------------------------------------------------------------
    !> the original text format (strain clamp fixed; strain only with SPEED_VTK_STRAIN=1)
    subroutine VTK_WRITE_ASCII(nn_loc, cs_nnz_loc, cs_loc, xx_loc, yy_loc, zz_loc, mpi_id, nmpi, &
                               nn, vtk_numbering_map, its, strain, disp)
      use speed_vtk_out
      implicit none
      integer*4, intent(in) :: nn_loc, cs_nnz_loc, mpi_id, nmpi, nn, its
      integer*4, dimension(0:cs_nnz_loc), intent(in) :: cs_loc
      integer*4, dimension(nn*nn*nn), intent(in) :: vtk_numbering_map
      real*8, dimension(nn_loc), intent(in) :: xx_loc, yy_loc, zz_loc
      real*8, dimension(6*nn_loc), intent(in) :: strain
      real*8, dimension(3*nn_loc), intent(in) :: disp
      character(len=80) :: fname, fmt
      integer :: u, i, ie, n3, nel_loc
      integer*4, allocatable :: conn(:)

      nel_loc = cs_loc(0) - 1
      n3 = nn*nn*nn
      write(fname,'(a,i8.8,a,i5.5,a)') './VTKOUT/SNAPSHOT_', its, '.', mpi_id, '.vtu'
      open(newunit=u, file=trim(fname), status='replace', action='write')
      write(u,'(a)') '<?xml version="1.0" encoding="utf-8"?>'
      write(u,'(a)') '<VTKFile type="UnstructuredGrid" version="0.1" byte_order="LittleEndian">'
      write(u,'(a)') '<UnstructuredGrid>'
      write(u,'(a,i0,a,i0,a)') '<Piece NumberOfPoints="', nn_loc, '" NumberOfCells="', nel_loc, '">'
      write(u,'(a)') '<Points>'
      write(u,'(a)') '<DataArray type="Float32" NumberOfComponents="3" format="ascii">'
      do i = 1, nn_loc
          write(u,'(3e20.12)') xx_loc(i), yy_loc(i), zz_loc(i)
      enddo
      write(u,'(a)') '</DataArray>'
      write(u,'(a)') '</Points>'
      write(u,'(a)') '<Cells>'
      write(u,'(a)') '<DataArray type="Int32" Name="connectivity" format="ascii">'
      allocate(conn(n3*nel_loc))
      call VTK_LOCAL_CONNECTIVITY(cs_nnz_loc, cs_loc, nn, vtk_numbering_map, nel_loc, conn)
      write(fmt,'(a,i0,a)') '(', n3, 'i12)'
      do ie = 1, nel_loc
          write(u,fmt) conn((ie-1)*n3+1 : ie*n3)
      enddo
      deallocate(conn)
      write(u,'(a)') '</DataArray>'
      write(u,'(a)') '<DataArray type="Int32" Name="offsets" format="ascii">'
      write(u,'(6i12)') (ie*n3, ie=1,nel_loc)
      write(u,'(a)') '</DataArray>'
      write(u,'(a)') '<DataArray type="Int32" Name="types" format="ascii">'
      write(u,'(6i12)') (72, ie=1,nel_loc)
      write(u,'(a)') '</DataArray>'
      write(u,'(a)') '</Cells>'
      write(u,'(a)') '<PointData>'
      if (vtk_strain) then
          write(u,'(a)') '<DataArray type="Float32" NumberOfComponents="6" Name="Strain" format="ascii">'
          do i = 1, nn_loc
              write(u,'(6e20.12)') to_f32(strain(6*i-5:6*i))
          enddo
          write(u,'(a)') '</DataArray>'
      endif
      write(u,'(a)') '<DataArray type="Float32" NumberOfComponents="3" Name="Disp" format="ascii">'
      do i = 1, nn_loc
          write(u,'(3e20.12)') to_f32(disp(3*i-2:3*i))
      enddo
      write(u,'(a)') '</DataArray>'
      write(u,'(a)') '</PointData>'
      write(u,'(a)') '</Piece>'
      write(u,'(a)') '</UnstructuredGrid>'
      write(u,'(a)') '</VTKFile>'
      close(u)

      if (mpi_id .eq. 0) call VTK_WRITE_PVTU(nmpi, its, .false.)
    end subroutine VTK_WRITE_ASCII


    !-----------------------------------------------------------------------------------------------
    !> XDMF + raw binary. Every rank sends its part to rank 0 (MPI_GATHERV); rank 0 writes
    !!   VTKOUT/mesh_points.bin  float64 (np_tot, 3)        once
    !!   VTKOUT/mesh_cells.bin   int32   (nc_tot, 8)        once, linear hexahedra, 0-based global ids
    !!   VTKOUT/Disp_<its>.bin   float32 (np_tot, 3)        every snapshot   [Strain_<its>.bin (np_tot, 6)]
    !!   VTKOUT/SPEED.xmf        temporal collection; one <Grid> is added per snapshot
    !! The partitions are simply put one after the other (nodes on partition borders appear twice).
    subroutine VTK_WRITE_XDMF(nn_loc, cs_nnz_loc, cs_loc, xx_loc, yy_loc, zz_loc, mpi_id, nmpi, &
                              nn, its, strain, disp)
      use speed_vtk_out
      implicit none
      include 'SPEED.MPI'
      integer*4, intent(in) :: nn_loc, cs_nnz_loc, mpi_id, nmpi, nn, its
      integer*4, dimension(0:cs_nnz_loc), intent(in) :: cs_loc
      real*8, dimension(nn_loc), intent(in) :: xx_loc, yy_loc, zz_loc
      real*8, dimension(6*nn_loc), intent(in) :: strain
      real*8, dimension(3*nn_loc), intent(in) :: disp

      integer*4 :: ierr, i, ie, a, b, c, k, nel_loc, nsub, r, u
      integer*4, allocatable :: np_r(:), nc_r(:), ne_r(:), cnt(:), dsp(:), cells(:), cells_all(:), elem(:), elem_all(:)
      real*8, allocatable :: xyz(:), xyz_all(:)
      real*4, allocatable :: f_loc(:), f_all(:)
      real*4 :: dummy4(1)
      real*8 :: dummy8(1)
      integer*4 :: dummyi(1)
      character(len=40) :: fdisp, fstrain
      real*8 :: tval

      nel_loc = cs_loc(0) - 1
      nsub = (nn-1)**3                                   ! linear hexahedra per spectral element
      allocate(np_r(nmpi), nc_r(nmpi), ne_r(nmpi), cnt(nmpi), dsp(nmpi))
      call MPI_GATHER(nn_loc, 1, MPI_INTEGER, np_r, 1, MPI_INTEGER, 0, SPEED_COMM, ierr)

      ! ---- mesh: once
      if (.not. vtk_mesh_done) then
          call MPI_GATHER(nsub*nel_loc, 1, MPI_INTEGER, nc_r, 1, MPI_INTEGER, 0, SPEED_COMM, ierr)
          call MPI_GATHER(nel_loc, 1, MPI_INTEGER, ne_r, 1, MPI_INTEGER, 0, SPEED_COMM, ierr)
          allocate(xyz(3*nn_loc))
          do i = 1, nn_loc
              xyz(3*i-2) = xx_loc(i)
              xyz(3*i-1) = yy_loc(i)
              xyz(3*i)   = zz_loc(i)
          enddo
          ! local GLL index of node (i,j,k) of an element: nn*nn*(k-1) + nn*(j-1) + i  (as in VTK_NODE_NUMBERING_MAP).
          ! VTK axes of the element there: r along k, s along -i, t along -j; sub-cell corners in VTK order.
          allocate(cells(8*nsub*nel_loc))
          k = 0
          do ie = 1, nel_loc
              do c = 1, nn-1
                  do b = 1, nn-1
                      do a = 1, nn-1
                          cells(k+1) = gll(a,   b,   c  )
                          cells(k+2) = gll(a+1, b,   c  )
                          cells(k+3) = gll(a+1, b+1, c  )
                          cells(k+4) = gll(a,   b+1, c  )
                          cells(k+5) = gll(a,   b,   c+1)
                          cells(k+6) = gll(a+1, b,   c+1)
                          cells(k+7) = gll(a+1, b+1, c+1)
                          cells(k+8) = gll(a,   b+1, c+1)
                          k = k + 8
                      enddo
                  enddo
              enddo
          enddo
          ! the spectral elements themselves (8 corner nodes): the grid as in the mesh file, SPEED_elements.xmf
          allocate(elem(8*nel_loc))
          do ie = 1, nel_loc
              elem(8*ie-7) = gll(1,  1,  1 )
              elem(8*ie-6) = gll(nn, 1,  1 )
              elem(8*ie-5) = gll(nn, nn, 1 )
              elem(8*ie-4) = gll(1,  nn, 1 )
              elem(8*ie-3) = gll(1,  1,  nn)
              elem(8*ie-2) = gll(nn, 1,  nn)
              elem(8*ie-1) = gll(nn, nn, nn)
              elem(8*ie)   = gll(1,  nn, nn)
          enddo
          if (mpi_id .eq. 0) then
              vtk_np_tot = sum(np_r)
              vtk_nc_tot = sum(nc_r)
              vtk_ne_tot = sum(ne_r)
              allocate(xyz_all(3*vtk_np_tot), cells_all(8*vtk_nc_tot))
              cnt = 3*np_r
              call vtk_displs(nmpi, cnt, dsp)
              call MPI_GATHERV(xyz, 3*nn_loc, MPI_DOUBLE_PRECISION, xyz_all, cnt, dsp, MPI_DOUBLE_PRECISION, &
                               0, SPEED_COMM, ierr)
              cnt = 8*nc_r
              call vtk_displs(nmpi, cnt, dsp)
              call MPI_GATHERV(cells, 8*nsub*nel_loc, MPI_INTEGER, cells_all, cnt, dsp, MPI_INTEGER, &
                               0, SPEED_COMM, ierr)
              ! local -> global point ids: add the first point of each partition
              k = 0
              do r = 1, nmpi
                  cells_all(dsp(r)+1 : dsp(r)+cnt(r)) = cells_all(dsp(r)+1 : dsp(r)+cnt(r)) + k
                  k = k + np_r(r)
              enddo
              call vtk_write_raw8('./VTKOUT/mesh_points.bin', xyz_all, 3*vtk_np_tot)
              call vtk_write_raw4i('./VTKOUT/mesh_cells.bin', cells_all, 8*vtk_nc_tot)
              deallocate(xyz_all, cells_all)
              allocate(elem_all(8*vtk_ne_tot))
              cnt = 8*ne_r
              call vtk_displs(nmpi, cnt, dsp)
              call MPI_GATHERV(elem, 8*nel_loc, MPI_INTEGER, elem_all, cnt, dsp, MPI_INTEGER, 0, SPEED_COMM, ierr)
              k = 0
              do r = 1, nmpi
                  elem_all(dsp(r)+1 : dsp(r)+cnt(r)) = elem_all(dsp(r)+1 : dsp(r)+cnt(r)) + k
                  k = k + np_r(r)
              enddo
              call vtk_write_raw4i('./VTKOUT/mesh_elements.bin', elem_all, 8*vtk_ne_tot)
              deallocate(elem_all)
              call vtk_xmf_start('./VTKOUT/SPEED.xmf', vtk_xmf_pos)
              call vtk_xmf_start('./VTKOUT/SPEED_elements.xmf', vtk_xme_pos)
          else
              call MPI_GATHERV(xyz, 3*nn_loc, MPI_DOUBLE_PRECISION, dummy8, cnt, dsp, MPI_DOUBLE_PRECISION, &
                               0, SPEED_COMM, ierr)
              call MPI_GATHERV(cells, 8*nsub*nel_loc, MPI_INTEGER, dummyi, cnt, dsp, MPI_INTEGER, &
                               0, SPEED_COMM, ierr)
              call MPI_GATHERV(elem, 8*nel_loc, MPI_INTEGER, dummyi, cnt, dsp, MPI_INTEGER, 0, SPEED_COMM, ierr)
          endif
          deallocate(xyz, cells, elem)
          vtk_mesh_done = .true.
      endif

      ! ---- displacement (and strain) of this snapshot
      write(fdisp,'(a,i8.8,a)') 'Disp_', its, '.bin'
      write(fstrain,'(a,i8.8,a)') 'Strain_', its, '.bin'
      allocate(f_loc(3*nn_loc))
      f_loc = to_f32(disp)
      if (mpi_id .eq. 0) then
          allocate(f_all(3*vtk_np_tot))
          cnt = 3*np_r
          call vtk_displs(nmpi, cnt, dsp)
          call MPI_GATHERV(f_loc, 3*nn_loc, MPI_REAL, f_all, cnt, dsp, MPI_REAL, 0, SPEED_COMM, ierr)
          call vtk_write_raw4('./VTKOUT/'//trim(fdisp), f_all, 3*vtk_np_tot)
          deallocate(f_all)
      else
          call MPI_GATHERV(f_loc, 3*nn_loc, MPI_REAL, dummy4, cnt, dsp, MPI_REAL, 0, SPEED_COMM, ierr)
      endif
      deallocate(f_loc)
      if (vtk_strain) then
          allocate(f_loc(6*nn_loc))
          f_loc = to_f32(strain)
          if (mpi_id .eq. 0) then
              allocate(f_all(6*vtk_np_tot))
              cnt = 6*np_r
              call vtk_displs(nmpi, cnt, dsp)
              call MPI_GATHERV(f_loc, 6*nn_loc, MPI_REAL, f_all, cnt, dsp, MPI_REAL, 0, SPEED_COMM, ierr)
              call vtk_write_raw4('./VTKOUT/'//trim(fstrain), f_all, 6*vtk_np_tot)
              deallocate(f_all)
          else
              call MPI_GATHERV(f_loc, 6*nn_loc, MPI_REAL, dummy4, cnt, dsp, MPI_REAL, 0, SPEED_COMM, ierr)
          endif
          deallocate(f_loc)
      endif

      if (mpi_id .eq. 0) then
          tval = dble(its)                                          ! time step unknown: step number
          if (vtk_dt .gt. 0.d0) tval = its*vtk_dt
          call vtk_xmf_add('./VTKOUT/SPEED.xmf', vtk_xmf_pos, vtk_nc_tot, 'mesh_cells.bin', tval, trim(fdisp), trim(fstrain))
          call vtk_xmf_add('./VTKOUT/SPEED_elements.xmf', vtk_xme_pos, vtk_ne_tot, 'mesh_elements.bin', tval, &
                           trim(fdisp), trim(fstrain))
      endif
      deallocate(np_r, nc_r, ne_r, cnt, dsp)

    contains

      integer*4 function gll(ar, as, at)
        ! (r, s, t) index of the VTK axes -> 0-based local point id of the GLL node
        integer*4, intent(in) :: ar, as, at
        integer*4 :: gi, gj, gk
        gk = ar
        gi = nn + 1 - as
        gj = nn + 1 - at
        gll = cs_loc(cs_loc(ie-1) + nn*nn*(gk-1) + nn*(gj-1) + gi) - 1
      end function gll

    end subroutine VTK_WRITE_XDMF


    subroutine vtk_displs(n, cnt, dsp)
      implicit none
      integer*4, intent(in) :: n, cnt(n)
      integer*4, intent(out) :: dsp(n)
      integer*4 :: r
      dsp(1) = 0
      do r = 2, n
          dsp(r) = dsp(r-1) + cnt(r-1)
      enddo
    end subroutine vtk_displs


    subroutine vtk_write_raw8(fname, v, n)
      implicit none
      character(len=*), intent(in) :: fname
      integer*4, intent(in) :: n
      real*8, intent(in) :: v(n)
      integer :: u
      open(newunit=u, file=fname, access='stream', form='unformatted', status='replace', action='write')
      write(u) v
      close(u)
    end subroutine vtk_write_raw8


    subroutine vtk_write_raw4(fname, v, n)
      implicit none
      character(len=*), intent(in) :: fname
      integer*4, intent(in) :: n
      real*4, intent(in) :: v(n)
      integer :: u
      open(newunit=u, file=fname, access='stream', form='unformatted', status='replace', action='write')
      write(u) v
      close(u)
    end subroutine vtk_write_raw4


    subroutine vtk_write_raw4i(fname, v, n)
      implicit none
      character(len=*), intent(in) :: fname
      integer*4, intent(in) :: n
      integer*4, intent(in) :: v(n)
      integer :: u
      open(newunit=u, file=fname, access='stream', form='unformatted', status='replace', action='write')
      write(u) v
      close(u)
    end subroutine vtk_write_raw4i


    !> new .xmf with an empty temporal collection; remembers where the closing tags start
    subroutine vtk_xmf_start(fname, pos)
      implicit none
      character(len=*), intent(in) :: fname
      integer(kind=8), intent(out) :: pos
      character(len=1), parameter :: nl = char(10)
      integer :: u
      integer(kind=8) :: p
      open(newunit=u, file=fname, access='stream', form='unformatted', status='replace', action='write')
      write(u) '<?xml version="1.0" ?>'//nl
      write(u) '<!-- SPEED field output: open in ParaView (XDMF reader). SPEED.xmf = all GLL nodes (fine cells), '// &
               'SPEED_elements.xmf = the spectral elements of the mesh (same nodes and values) -->'//nl
      write(u) '<Xdmf Version="3.0">'//nl
      write(u) '<Domain>'//nl
      write(u) '<Grid Name="SPEED" GridType="Collection" CollectionType="Temporal">'//nl
      inquire(unit=u, pos=p)
      pos = p
      write(u) '</Grid>'//nl//'</Domain>'//nl//'</Xdmf>'//nl
      close(u)
    end subroutine vtk_xmf_start


    !> one more time step in an .xmf: written over the closing tags, which are then written again
    subroutine vtk_xmf_add(fname, pos, ncells, fcells, t, fdisp, fstrain)
      use speed_vtk_out
      implicit none
      character(len=*), intent(in) :: fname, fcells, fdisp, fstrain
      integer(kind=8), intent(inout) :: pos
      integer, intent(in) :: ncells
      real*8, intent(in) :: t
      character(len=1), parameter :: nl = char(10)
      character(len=24) :: ts, snp, snc
      integer :: u
      integer(kind=8) :: p
      write(ts, '(es16.8)') t
      write(snp, '(i0)') vtk_np_tot
      write(snc, '(i0)') ncells
      open(newunit=u, file=fname, access='stream', form='unformatted', status='old', action='readwrite')
      write(u, pos=pos) ' <Grid Name="mesh" GridType="Uniform">'//nl// &
          '  <Time Value="'//trim(adjustl(ts))//'"/>'//nl// &
          '  <Topology TopologyType="Hexahedron" NumberOfElements="'//trim(snc)//'">'//nl// &
          '   <DataItem Dimensions="'//trim(snc)//' 8" NumberType="Int" Precision="4" Format="Binary" Endian="Little">'// &
          fcells//'</DataItem>'//nl// &
          '  </Topology>'//nl// &
          '  <Geometry GeometryType="XYZ">'//nl// &
          '   <DataItem Dimensions="'//trim(snp)//' 3" NumberType="Float" Precision="8" Format="Binary" Endian="Little">'// &
          'mesh_points.bin</DataItem>'//nl// &
          '  </Geometry>'//nl// &
          '  <Attribute Name="Disp" AttributeType="Vector" Center="Node">'//nl// &
          '   <DataItem Dimensions="'//trim(snp)//' 3" NumberType="Float" Precision="4" Format="Binary" Endian="Little">'// &
          fdisp//'</DataItem>'//nl// &
          '  </Attribute>'//nl
      if (vtk_strain) then
          write(u) '  <Attribute Name="Strain" AttributeType="Matrix" Center="Node">'//nl// &
              '   <DataItem Dimensions="'//trim(snp)//' 6" NumberType="Float" Precision="4" Format="Binary" Endian="Little">'// &
              fstrain//'</DataItem>'//nl// &
              '  </Attribute>'//nl
      endif
      write(u) ' </Grid>'//nl
      inquire(unit=u, pos=p)
      pos = p
      write(u) '</Grid>'//nl//'</Domain>'//nl//'</Xdmf>'//nl
      close(u)
    end subroutine vtk_xmf_add


    !-----------------------------------------------------------------------------------------------
    !> called once by rank 0 at its = 0: remembers the time step (XDMF time values) and, for the
    !! .vtu formats, writes the ParaView collection SNAPSHOT.pvd as before
    subroutine WRITE_PVD_TIMEDATA(nmpi, nts, ncount, dt)
        use speed_vtk_out
        implicit none
        integer*4, intent(in) :: nmpi, nts, ncount
        real*8 :: dt
        integer*4 :: unit_mpi, i
        character*70 :: filename_pvtu, filename_pvd, str_time
        character*200 :: buffer

        vtk_dt = dt
        call vtk_settings()
        if (vtk_mode .eq. 2) return                       ! XDMF: the time values are in SPEED.xmf

        write(filename_pvd,'(a)') './VTKOUT/SNAPSHOT.pvd'
        open(newunit=unit_mpi, file=filename_pvd, status='replace', action='write')
        buffer='<?xml version="1.0" encoding="utf-8"?>'
        write(unit_mpi,'(a)')trim(buffer)
        buffer='<VTKFile type="Collection" version="0.1" byte_order="LittleEndian">'
        write(unit_mpi,'(a)')trim(buffer)
        buffer='<Collection>'
        write(unit_mpi,'(a)')trim(buffer)
        do i=0,nts,ncount
            write(filename_pvtu,'(a,i8.8,a)') './SNAPSHOT_',i,'.pvtu'
            write(str_time,'(f16.6)') i*dt
            buffer='<DataSet timestep="'//trim(adjustl(str_time))//'" part="001" file="'//trim(filename_pvtu)//'"/>'
            write(unit_mpi,'(a)')trim(buffer)
        enddo
        buffer='</Collection>'
        write(unit_mpi,'(a)')trim(buffer)
        buffer='</VTKFile>'
        write(unit_mpi,'(a)')trim(buffer)
        close(unit_mpi)
    end subroutine WRITE_PVD_TIMEDATA


    !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    ! (unchanged) Maps the conversion -> speed node numbering to VTK nodenumbering for VTK_LAGRANGE_HEXAHEDRAN of order n
    ! Reference: https://www.kitware.com/main/wp-content/uploads/2018/09/Source_Issue_43.pdf
    ! https://gitlab.kitware.com/vtk/vtk/-/issues/17746
    subroutine VTK_NODE_NUMBERING_MAP(nn, vtk_numbering)  
  
        integer*4, intent(in) :: nn
        integer*4, dimension(nn*nn*nn), intent(out) :: vtk_numbering

        integer*4 :: i, j, k, i1, i2, i3, ncount
       
        vtk_numbering = 0;

        if (nn.le.1) call exit()

        ! 8 Vertices (first 4 belong to bottom face), next 4 belong to top face
        k= 1; j=nn; i=nn;  vtk_numbering(1) = nn*nn*(k-1) + nn*(j-1) + i;
        k=nn; j=nn; i=nn;  vtk_numbering(2) = nn*nn*(k-1) + nn*(j-1) + i;
        k=nn; j=nn; i= 1;  vtk_numbering(3) = nn*nn*(k-1) + nn*(j-1) + i;
        k= 1; j=nn; i= 1;  vtk_numbering(4) = nn*nn*(k-1) + nn*(j-1) + i;

        k= 1; j= 1; i=nn;  vtk_numbering(5) = nn*nn*(k-1) + nn*(j-1) + i;
        k=nn; j= 1; i=nn;  vtk_numbering(6) = nn*nn*(k-1) + nn*(j-1) + i;
        k=nn; j= 1; i= 1;  vtk_numbering(7) = nn*nn*(k-1) + nn*(j-1) + i;
        k= 1; j= 1; i= 1;  vtk_numbering(8) = nn*nn*(k-1) + nn*(j-1) + i;

        if (nn.le.2) return

        ! 12 Edges
        do i1 = 2,(nn-1)
            !Bottom face
            ! Edge 1 - Bottom - X1
            k=i1; j=nn; i=nn;  vtk_numbering(8 + i1 -1) = nn*nn*(k-1) + nn*(j-1) + i;

            ! Edge 2 - Bottom - Y2
            k=nn; j=nn; i=nn-i1+1;  vtk_numbering(8 + (nn-2) + i1 -1) = nn*nn*(k-1) + nn*(j-1) + i;

            ! Edge 3 - Bottom - X2
            k=i1; j=nn; i= 1;  vtk_numbering(8 + 2*(nn-2) + i1 -1) = nn*nn*(k-1) + nn*(j-1) + i;

            ! Edge 4 - Bottom - Y2
            k= 1; j=nn; i=nn-i1+1;  vtk_numbering(8 + 3*(nn-2) + i1-1) = nn*nn*(k-1) + nn*(j-1) + i;


            !Top Face
            ! Edge 5 - Top - X1
            k=i1; j= 1; i=nn;  vtk_numbering(8 + 4*(nn-2) + i1-1) = nn*nn*(k-1) + nn*(j-1) + i;

            ! Edge 6 - Top - Y2
            k=nn; j= 1; i=nn-i1+1;  vtk_numbering(8 + 5*(nn-2) + i1-1) = nn*nn*(k-1) + nn*(j-1) + i;

            ! Edge 7 - Top - X2
            k=i1; j= 1; i= 1;  vtk_numbering(8 + 6*(nn-2) + i1-1) = nn*nn*(k-1) + nn*(j-1) + i;

            ! Edge 8 - Top - Y2
            k= 1; j= 1; i=nn-i1+1;  vtk_numbering(8 + 7*(nn-2) + i1-1) = nn*nn*(k-1) + nn*(j-1) + i;


            !Vertical Edges
            ! Edge 9 - front-left
            k= 1; j=nn-i1+1; i=nn;  vtk_numbering(8 + 8*(nn-2) + i1-1) = nn*nn*(k-1) + nn*(j-1) + i;

            ! Edge 10 - front-right
            k=nn; j=nn-i1+1; i=nn;  vtk_numbering(8 + 9*(nn-2) + i1-1) = nn*nn*(k-1) + nn*(j-1) + i;

            ! Edge 11 - back-left
            k= 1; j=nn-i1+1; i= 1;  vtk_numbering(8 + 10*(nn-2) + i1-1) = nn*nn*(k-1) + nn*(j-1) + i;

            ! Edge 12 - back-right
            k=nn; j=nn-i1+1; i= 1;  vtk_numbering(8 + 11*(nn-2) + i1-1) = nn*nn*(k-1) + nn*(j-1) + i;
        enddo


        !Other Exterior nodes present on 6 faces
        ncount = 0;
        do i1 = 2,(nn-1)
            do i2 = 2,(nn-1)
                ncount = ncount+1;

                !1st Face - side left (Xmin)
                k= 1; j=nn-i1+1; i=nn-i2+1;  vtk_numbering(8 + 12*(nn-2) + ncount) = nn*nn*(k-1) + nn*(j-1) + i;

                !2nd Face - side left (Xmax)
                k=nn; j=nn-i1+1; i=nn-i2+1;  vtk_numbering(8 + 12*(nn-2) + 1*(nn-2)*(nn-2) + ncount) = nn*nn*(k-1) + nn*(j-1) + i;

                !3rd Face - front (Ymin)
                k=i2; j=nn-i1+1; i=nn;  vtk_numbering(8 + 12*(nn-2) + 2*(nn-2)*(nn-2) + ncount) = nn*nn*(k-1) + nn*(j-1) + i;

                !4th Face - Back (Ymax)
                k=i2; j=nn-i1+1; i= 1;  vtk_numbering(8 + 12*(nn-2) + 3*(nn-2)*(nn-2) + ncount) = nn*nn*(k-1) + nn*(j-1) + i;

                !5th Face - Bottom (Zmin)
                k=i2; j=nn; i=nn-i1+1;  vtk_numbering(8 + 12*(nn-2) + 4*(nn-2)*(nn-2) + ncount) = nn*nn*(k-1) + nn*(j-1) + i;

                !6th Face - Top (Zmax)
                k=i2; j=1; i=nn-i1+1;  vtk_numbering(8 + 12*(nn-2) + 5*(nn-2)*(nn-2) + ncount) = nn*nn*(k-1) + nn*(j-1) + i;
            enddo
        enddo

        ! Volume nodes
        ncount = 0;
        do i1=2,(nn-1)
            do i2=2,(nn-1)
                do i3=2,(nn-1)
                    ncount=ncount+1;
                    k=i3; j=nn-i1+1; i=nn-i2+1;  vtk_numbering(8 + 12*(nn-2) + 6*(nn-2)*(nn-2) + ncount) = nn*nn*(k-1) + nn*(j-1) + i;
                enddo
            enddo
        enddo
      
    end subroutine VTK_NODE_NUMBERING_MAP  

    